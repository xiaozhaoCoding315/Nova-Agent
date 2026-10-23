# Nova Agent v2 重构设计文档

> 版本：2026-10-23 · 状态：已确认方向，进入实现
> 决策记录：激进聚焦（砍 Neo4j / DAG / 评测 / 图谱前端）；数据层 = Qdrant 稠密 + PostgreSQL 关键词（砍 Neo4j，不用 pgvector）；先本地开发（连 192.168.150.128 VM 上的 PG/Qdrant），部署形态保持"一条命令可拉起"；认证面向"面试官可访问、也可给别人用"。

---

## 1. 产品定位

**一句话**：Nova Agent 是一个可自托管的开发者 AI 工作台——读懂你的代码、定位你的报错、验证你的代码、处理日常杂活。

### 1.1 服务的四个真实工作流

| 工作流 | 用户场景（原话） | Agent 能力 | 可验证性 |
|---|---|---|---|
| **读代码** | "X 功能在哪个文件实现的？""这个请求的完整链路是什么？" | 导入仓库（zip / 公开 git）→ 符号级索引 → 混合检索 → 回答携带 `文件:行号` 引用 | 引用可点击、片段可核对 |
| **查报错** | 贴一段 Python/JVM/Node 堆栈或日志 | 解析堆栈帧 → 在仓库中定位对应代码 → 交叉检索历史经验 → 给出修复建议 → 沙箱复现 | 定位到真实文件行号；复现结果可见 |
| **验证代码** | "帮我写个测试""这段代码对不对""为什么输出不对" | LLM 写代码 → 沙箱执行 → 读取真实结果 → 自我纠错迭代（≤5 轮） | 执行结果是真实的 stdout/exit code |
| **日常杂活** | JSON/YAML 转换、SQL 审阅、抓取文档链接 | json/sql/fetch 工具，全部有确定性实现 | 工具输出即真相 |

### 1.2 明确不做（非目标）

- 不做通用聊天助手（无仓库上下文的闲聊不是产品重点）
- 不做 DAG 任务可视化面板、RAG 评测平台、记忆图谱大屏——v1 的演示型功能全部退场
- 不做多租户 SaaS：账号体系服务于"面试官演示 + 小范围分享"，不是开放注册平台
- 不引入 LangChain/LangGraph 等框架：Agent 循环自研，行为可控可调试

---

## 2. 架构总览

### 2.1 部署拓扑（生产 = 本地开发同构）

```
                    ┌──────────────────────────────┐
   浏览器 ────────▶ │  app 容器（FastAPI + dist 静态托管）│
                    │   ├─ 认证中间件 / 限流 / 配额      │
                    │   ├─ Chat SSE 管线（Agent 循环）   │
                    │   ├─ 工作区索引管线               │
                    │   └─ 工具执行（含沙箱调度）        │
                    └───────┬───────────────┬───────┘
                            │               │ docker.sock（可选，仅沙箱用）
                    ┌───────▼──────┐  ┌─────▼──────────┐
                    │ PostgreSQL    │  │ 沙箱容器（一次性）│
                    │ 业务/会话/记忆 │  │ --network none   │
                    │ 分块全文(jieba)│  │ --read-only ...  │
                    └──────────────┘  └────────────────┘
                    ┌──────────────┐
                    │ Qdrant        │
                    │ 稠密向量(code_chunks) │
                    └──────────────┘
```

- **本地开发**：backend 以本机进程运行（Windows 下热改代码），PG/Qdrant 连 VM `192.168.150.128`；沙箱需本机 Docker Desktop 运行。
- **容器部署**：`docker compose up -d` 拉起 app + postgres + qdrant 三个容器；沙箱通过挂载 docker.sock 启动兄弟容器（禁用网络/只读/丢弃权限）。沙箱不可用时工具如实标记为不可用，**绝不降级为宿主机直接执行**。

### 2.2 一次对话的请求时序

```
POST /api/v1/chat/message (SSE)
  1. 鉴权 + 限流 + 配额检查（超限 → 429/SSE error 事件）
  2. 落库用户消息；缺失 session 则创建（标题自动生成）
  3. 检索：Qdrant 稠密 ∥ PG 关键词（jieba）→ RRF 融合（选中仓库时检索其分块；未选仓库则只走通用召回）
  4. 组装上下文：系统提示词 + 仓库引用片段 + 长期记忆 facts + 最近会话消息（超长→摘要）
  5. Agent 循环（≤5 轮）：
       LLM 流式生成（90s 超时，harness 保护）
         有 tool_calls → 逐个执行（每个 30s 超时、重试、熔断）
                       → SSE 推 tool_call / tool_result
                       → 结果回填 messages → 下一轮
         无 tool_calls → 流式 token 结束
  6. 落库 assistant 消息（含工具调用记录、真实 token usage）
  7. SSE done（message_id / 耗时 / tools_used / usage）
  客户端断开 → 本轮生成取消，已生成部分落库
```

### 2.3 后端模块职责

| 模块 | 职责 | 来源 |
|---|---|---|
| `api/v1/auth.py` | 登录/登出/me | 新增 |
| `api/v1/chat.py` | 会话 CRUD + SSE 对话 | 重写 |
| `api/v1/repos.py` | 工作区导入/列表/文件树/文件内容/符号搜索/重索引 | 新增（吸收旧 knowledge） |
| `api/v1/status.py` | 真实健康检查（PG/Qdrant/LLM/沙箱探活）、用量统计 | 重写（吸收旧 health/admin） |
| `core/agent/loop.py` | Agent 主循环（工具轮次编排、停止语义） | 重写（替代 dag/decomposer/race） |
| `core/rag/` | 双路召回 + RRF | 保留收编（删 graph 路） |
| `core/indexing/` | 导入 → 遍历 → 符号提取 → 分块 → 双写 | 新增（升级 text_splitter） |
| `core/memory/` | 会话消息 + 长期 facts（抽取/去重/衰减） | 保留收编（删图谱层） |
| `core/tools/` | 工具注册表 + 6 个工具 | 重写扩展 |
| `core/sandbox/` | Docker-only 执行器 | 重写（删危险兜底、修 kill bug） |
| `core/harness/` | 超时/重试/熔断 | 保留（补接 LLM 超时） |
| `core/security/` | JWT/密码、限流配额、风险规则、审计 | 重写扩展 |
| `core/llm/` | 多厂商工厂 + 顺序降级 + 工具流式 | 保留（删竞速） |
| `core/embedding/` | DashScope text-embedding-v3（1024 维） | 保留 |
| `db/` | PG 连接池 + Qdrant 客户端 + 幂等初始化 | 重写（删 neo4j） |

---

## 3. 技术选型与理由

| 选型 | 理由 |
|---|---|
| PostgreSQL（关键词 + 全部业务数据） | 一库承载会话/记忆/工作区/用量；jieba 预处理 + tsvector 实现中文关键词检索，ILIKE 兜底 |
| Qdrant（稠密向量） | 已有稳定集成；按 `repo_id` payload 过滤；单集合 `code_chunks` |
| 彻底删 Neo4j | v1 图谱记忆靠硬编码关键词+正则抽实体，召回≈0；Neo4j 内存开销 1-2GB，与"小服务器可跑"冲突 |
| 不用 pgvector | 稠密检索已由 Qdrant 承担，避免双实现；PG 只做关键词与业务 |
| FastAPI + 自研 Agent 循环 | 行为可控、可测试；不引入 LangChain 黑盒 |
| React 18 + TS + Vite + Zustand | 沿用；新增 react-markdown + highlight.js（开发者刚需） |
| JWT（httpOnly cookie） + bcrypt | 前端零 token 管理；fetch-SSE 天然带 cookie |

---

## 4. 数据模型（PostgreSQL）

```sql
users        (id, username UNIQUE, password_hash, role CHECK IN ('admin','demo'), created_at)
sessions     (id UUID PK, user_id→users, title, summary TEXT,     -- 归档=摘要，v1 清空消息的 bug 在此修复
              created_at, updated_at)
messages     (id BIGSERIAL, session_id→sessions, role, content,
              tool_json JSONB, prompt_tokens INT, completion_tokens INT, created_at)
facts        (id BIGSERIAL, user_id→users, content, hash UNIQUE,   -- 长期记忆
              embedding JSONB, importance REAL, last_used_at, ttl_days INT, created_at)
repos        (id UUID PK, user_id→users, name, source TEXT,        -- source: zip|git
              root_path TEXT, status TEXT, error TEXT,             -- pending|indexing|ready|failed
              stats JSONB, created_at, updated_at)
repo_files   (id BIGSERIAL, repo_id→repos, path, language, size, line_count, is_doc BOOL)
symbols      (id BIGSERIAL, repo_id, file_id→repo_files, kind,     -- function|class|method|interface...
              name, parent, line_start, line_end, signature)
chunks       (id BIGSERIAL, repo_id, file_id→repo_files, content,
              line_start, line_end, lang, kind,                    -- code|doc
              tsv TSVECTOR)                                        -- GIN 索引，jieba 预处理
usage_log    (id BIGSERIAL, user_id, session_id, model,            -- 配额与用量统计底座
              prompt_tokens, completion_tokens, tool_calls INT, created_at)
audit_log    (id BIGSERIAL, user_id, action, detail JSONB, created_at)
```

Qdrant：集合 `code_chunks`，向量 1024 维（cosine），payload `{repo_id, file_id, path, line_start, line_end, lang}`。
索引策略：`chunks.tsv` GIN；`repo_files(repo_id, path)`；`usage_log(user_id, created_at)`；`facts(hash)`。

**迁移原则（对 VM 现存库）**：使用新数据库名 `nova_agent`（旧库 `novatech` 原样保留作备份），Qdrant 新集合 `code_chunks`（旧集合保留）。全部 DDL 幂等，启动时可 `AUTO_INIT_DB=true` 自动建表。

---

## 5. API 设计

### 5.1 REST

| 端点 | 说明 |
|---|---|
| `POST /api/v1/auth/login` / `logout` / `GET me` | 登录（签发 httpOnly JWT）/ 登出 / 当前用户 |
| `GET/POST /api/v1/chat/sessions` | 会话列表 / 新建 |
| `GET /api/v1/chat/sessions/{id}/messages` | 历史消息（v1 缺失，刷新丢记录的问题在此修复） |
| `DELETE /api/v1/chat/sessions/{id}` | 删除会话 |
| `POST /api/v1/chat/message` | **SSE 对话**（见 5.2） |
| `POST /api/v1/repos` | 导入工作区：`multipart zip` 或 `{git_url}` |
| `GET /api/v1/repos` / `GET /repos/{id}` / `DELETE /repos/{id}` | 列表（含索引进度）/ 详情 / 删除 |
| `GET /api/v1/repos/{id}/tree` | 文件树 |
| `GET /api/v1/repos/{id}/file?path=` | 文件内容（代码查看器） |
| `GET /api/v1/repos/{id}/search?q=` | 符号 + 混合检索（带 file:line） |
| `POST /api/v1/repos/{id}/reindex` | 重建索引 |
| `GET /api/v1/status/health` | 真实探活：PG / Qdrant / LLM / 沙箱逐项上报 |
| `GET /api/v1/status/usage` | 今日/累计用量、配额剩余 |
| `GET /api/v1/status/sandbox` | 沙箱可用性与镜像状态 |

### 5.2 SSE 事件协议（`POST /chat/message`）

| 事件 | 载荷 | 说明 |
|---|---|---|
| `meta` | `{session_id, title}` | 首帧；新建会话时标题为自动摘要 |
| `retrieval` | `{hits:[{path,line_start,line_end,score,source}]}` | 检索命中（前端渲染引用卡片） |
| `token` | `{text}` | 流式正文 |
| `tool_call` | `{id,name,args,round}` | 工具调用开始 |
| `tool_result` | `{id,name,ok,ms,preview}` | 工具调用结束（含耗时与结果预览） |
| `usage` | `{model,prompt_tokens,completion_tokens}` | 真实 token 用量（API 返回值，非字符估算） |
| `error` | `{code,message}` | 可解释错误（LLM 超时/配额超限/工具熔断） |
| `done` | `{message_id,elapsed_ms,tools_used}` | 结束帧 |

停止生成：前端 AbortController 断流 → 后端检测 `request.is_disconnected()` 取消本轮生成，部分输出落库，不产生 error 事件。

---

## 6. Agent 核心设计

### 6.1 循环（`core/agent/loop.py`）

```
async def run(session, user_msg, repo_ids) -> AsyncIterator[SSEEvent]:
    yield meta(...)
    hits = await retrieve(user_msg, repo_ids)        # harness: 10s 超时, 失败降级空
    yield retrieval(hits)
    messages = build_context(system, hits, facts, recent_messages, summary)
    for round in range(MAX_ROUNDS=5):
        stream = llm.astream_with_tools(messages, tools)   # harness: 90s 超时
        collect text / tool_calls from deltas  (yield token / tool_call)
        若无 tool_calls: break
        执行工具: results = [run_tool(tc) for tc in tool_calls]   # 每个 30s 超时+重试+熔断
                            (yield tool_result)
        messages += [assistant(tool_calls), *tool_messages(results)]
    persist(assistant_msg, tool_json, usage)   # usage 来自 API 返回
    yield done(...)
```

### 6.2 工具集（6 个，全部确定性实现）

| 工具 | 入参 | 行为与边界 |
|---|---|---|
| `run_code` | `{files:{path:content}, command?, stdin?}` | Docker 沙箱执行；镜像 `nova-sandbox:latest`（python3.12 + numpy + pytest）；`--network none --read-only --cap-drop ALL --pids-limit 64 -m 256m`；30s 超时按容器名 kill；无 Docker → 返回"沙箱不可用"，绝不直跑 |
| `diagnose_error` | `{stack, context?}` | 解析 Python/JVM/Node 堆栈帧（类型/消息/位置）；对帧中路径与符号在仓库中反查；输出结构化诊断 + 建议 |
| `search_code` | `{query, repo_id?}` | 双路混合检索 + 符号精确匹配；返回 `path:line` 片段（Agent 按需取码，补充自动召回） |
| `json_tool` | `{input, mode, path?}` | JSON/YAML：validate / format / extract(路径取值) / convert |
| `sql_tool` | `{sql, mode}` | format（格式化）+ review（静态审阅：SELECT *、UPDATE/DELETE 无 WHERE、隐式类型比较、前缀 LIKE 等） |
| `fetch_url` | `{url}` | 抓取公开文档 → 转 Markdown；SSRF 防护：仅 http/https、拒私网/环回/链路本地、≤3 跳重定向逐跳校验、512KB 上限、10s 超时 |

工具基础设施（沿用并收紧）：JSON Schema 校验入参、统一异常包装（工具永不抛穿主链路）、harness 包装执行、调用写审计、业务性校验失败不计入熔断统计。

### 6.3 系统提示词结构

```
身份：你是 Nova，一个严谨的开发者助手。
规则：
1. 引用代码必须给出 文件:行号，不臆造代码
2. 涉及"运行/验证"必须用 run_code 真实执行，不猜测输出
3. 报错分析先 diagnose_error 再回答
4. 工具失败如实说明，不编造结果
仓库上下文：<检索片段，带 path:line>
用户长期偏好：<facts>
```

---

## 7. 检索与索引

### 7.1 导入管线（`core/indexing/`）

```
zip 上传 / git clone --depth 1（公开仓库，超时 120s，大小上限 100MB）
  → 安全校验（zip-slip 防护、文件数上限 5000、单文件 2MB、二进制跳过）
  → 遍历过滤（跳 node_modules/.venv/.git/dist；扩展名白名单 20+ 语言 + md/txt/pdf）
  → 符号提取：Python 用 ast；Java/TS/JS/Go 等正则启发式（class/interface/function/方法）
  → 分块：代码按函数/类边界（超长再切，携带起止行号）；文档按段落
  → 双写：chunks → PG（jieba 预处理写 tsv）+ embeddings → Qdrant（payload 带 repo_id）
  → 状态机 pending → indexing → ready/failed（失败原因落库，前端可见）
```

### 7.2 双路召回 + RRF

- 稠密：Qdrant `code_chunks`（repo 过滤），top 10
- 关键词：PG `tsv @@ plainto_tsquery`（jieba 分词后），ILIKE 兜底中文边界，top 10
- RRF（k=10）融合 → top 5 注入上下文；单路故障降级为单路结果，全失败返回空
- 引用一律携带 `path / line_start / line_end`，前端可点击

---

## 8. 记忆设计（两层）

| 层 | 位置 | 生命周期 |
|---|---|---|
| 会话记忆 | `sessions` + `messages` | 持久；超 20 条自动 LLM 摘要进 `sessions.summary`，最近 10 条原文保留（v1 直接删消息的 bug 修复） |
| 长期记忆 | `facts` | 对话中异步抽取用户偏好/事实；MD5 + embedding 去重（0.92）；重要性衰减：命中 +0.1、7 天未用 −0.01、TTL 到期清理（小时级清理循环接上衰减，v1 定义了但没调用） |

图谱记忆（Neo4j）、DAG 运行时记忆随子系统一并退场。

---

## 9. 安全与配额

| 面 | 设计 |
|---|---|
| 认证 | JWT（httpOnly cookie，SameSite=Lax，7 天）；bcrypt 密码哈希；启动时从 env 幂等注入 `admin` 与 `demo` 两个账号；除 `/auth/login`、`/status/health` 外全部接口强制鉴权 |
| 角色 | `admin`：全功能；`demo`：全功能但限额更紧，供面试官/朋友访问（README 公开演示账号） |
| 限流 | 进程内令牌桶：admin 60 条/小时，demo 10 条/小时；超限 429 |
| 配额 | 每日 token 预算（usage_log 聚合）：demo 100k tokens/天，沙箱 20 次/天；admin 可配 |
| 沙箱 | Docker-only（见 6.2）；risk.py 风险正则保留为二次校验；全量审计 |
| SSRF | fetch_url 逐跳校验（见 6.2） |
| 上传 | zip-slip 防护、大小/文件数上限；git 仅公开仓库 |
| 审计 | 登录、对话、工具调用、导入、删除全量落 `audit_log` |

---

## 10. 前端设计（三视图）

```
LoginView ──成功──▶ App
├── ChatView      （左：会话列表 | 中：消息流 | 右：引用面板）
│    组件: SessionList / MessageList / MessageBubble / Markdown(代码高亮+复制)
│          ToolCard / ReferenceCard(点击展开片段) / Composer(停止按钮) / RepoSelector
├── WorkspaceView （仓库列表 + 导入对话框 + 文件树 + 代码查看器 + 索引进度）
└── SettingsView  （健康状态(真实探活) / 用量与配额 / 沙箱状态 / 账号信息）
```

关键交互（v1 缺失清单逐项修复）：

- Markdown 渲染 + 代码高亮（highlight.js）+ 一键复制代码
- 停止生成（AbortController）；请求失败渲染错误气泡并恢复输入框（v1 死锁 bug）
- 刷新恢复会话（拉取历史接口）；"新建对话"按钮
- 引用卡片：`path:line` → 点击展开代码片段 → 可跳转 Workspace 查看
- 头部状态灯接真实 `/status/health`（v1 是写死的假 ONLINE）
- 所有请求带错误态与重试，删掉全部"失败伪造数据"兜底（v1 taskStore 伪造 DAG 等）

删除：particles/three.js、memory/eval/tasks/admin 面板与相关 store、framer-motion、axios（改用 fetch）。

---

## 11. 部署与环境

### 11.1 本地开发（当前阶段）

```bash
# VM 192.168.150.128 提供 PG + Qdrant（需开机）；后端本机运行
cd backend && python run.py            # http://localhost:8000
cd frontend && npm run dev             # http://localhost:5173（代理到 8000）
# 沙箱工具需要本机 Docker Desktop 运行；未运行时 /status/sandbox 如实上报
```

`backend/.env`：PG/Qdrant 指向 VM；新库名 `nova_agent`（首次启动 AUTO_INIT_DB=true 幂等建表）。

### 11.2 生产（租到服务器后）

```bash
cp .env.example .env   # LLM keys / ADMIN_PASSWORD / DEMO_PASSWORD / SECRET_KEY
docker compose up -d --build   # app + postgres + qdrant（+ sandbox 镜像构建）
```

- app 容器：多阶段构建（node 构建前端 → python 运行）；挂载 `/var/run/docker.sock` 供沙箱；非 root 运行
- 可选 Caddy 反代 profile（域名到位后一行开启 HTTPS）
- 健康检查：compose healthcheck 指向真实探活的 `/status/health`

### 11.3 环境变量清单（新增/变更）

`ADMIN_USERNAME/ADMIN_PASSWORD/DEMO_USERNAME/DEMO_PASSWORD`、`MAX_ROUNDS`、`LLM_TIMEOUT`、`DEMO_DAILY_TOKENS`、`DEMO_SANDBOX_DAILY`、`POSTGRES_DB=nova_agent`；删除 `NEO4J_*`。

---

## 12. 目录结构（目标形态）

```
backend/app/
├── api/v1/   auth.py chat.py repos.py status.py router.py
├── core/
│   ├── agent/loop.py
│   ├── rag/{retriever,dense,keyword,rrf}.py
│   ├── indexing/{pipeline,walker,chunker,symbols}.py
│   ├── memory/{session,facts,context}.py
│   ├── tools/{base,run_code,diagnose,search_code,json_tool,sql_tool,fetch_url}.py
│   ├── sandbox/runtime.py
│   ├── harness/{runtime,retry,circuit,config}.py
│   ├── security/{auth,limits,risk,audit}.py
│   ├── llm/{factory,fallback,base}.py
│   └── embedding/embedder.py
├── db/{postgres,qdrant,init_db}.py
├── models/schemas.py
└── utils/{chinese_analyzer,text.md}.py
frontend/src/
├── views/{LoginView,ChatView,WorkspaceView,SettingsView}.tsx
├── components/{chat,workspace,common}/
├── hooks/useSSE.ts
├── services/api.ts
├── stores/{authStore,chatStore,repoStore}.ts
└── styles/
```

---

## 13. v1 → v2 处置清单

| 保留（收编/强化） | 重写 | 删除 |
|---|---|---|
| harness 容错引擎（补接 LLM 超时） | chat SSE 管线（超时/用量/停止/历史） | 全部 DAG：dag/decomposer/race/state*/task_store + /tasks API + TaskPanel/DAGCanvas |
| rag 双路（dense/keyword/RRF） | sandbox（删直跑兜底、修 kill、Docker-only） | Neo4j：db/neo4j.py、graph_memory、graph RAG 路、/graph API、记忆图谱前端 |
| memory 会话+facts（摘要归档替代清空） | tools 注册表与工具集（6 个） | evaluation/ 全部 + EvalPanel + dataset API |
| llm factory/fallback | config（去 LAN 默认、加认证/配额项） | 前端 particles/three.js/framer/axios/若干死组件与 store |
| indexing 复用 text_splitter/chinese_analyzer | init_db（新 schema） | security/validator（未接入的孤儿） |
| security risk/audit、embedding | 前端三视图（全新） | TaskStateMachine（59 个测试测死代码）、RaceStrategy |
| harness 的 retry/circuit | health（真实探活） | 旧 knowledge API（并入 repos） |

---

## 14. 实施计划与验收

| Phase | 内容 | 验收标准 |
|---|---|---|
| **0 地基** | 新分支；config/schema/init_db 重写；清除死代码；目录重排；依赖清理 | 本机起服务，`/status/health` 逐项探活真实上报 |
| **1 认证** | JWT + bcrypt + 两角色注入 + 限流 + 配额 | 未登录 401；demo 超限 429；admin 全通 |
| **2 会话与对话** | 会话 CRUD + 历史接口 + SSE v2（超时/用量/停止/错误事件）+ 两层记忆 | 刷新恢复历史；停止生成可用；token 为真实值 |
| **3 工作区** | 导入（zip/git）+ 索引管线 + 符号表 + 文件树/查看器 + 检索引用 | 导入真实仓库后可回答"X 在哪"并给出真实 file:line |
| **4 工具与沙箱** | 6 工具 + Docker-only 沙箱 + SSRF 防护 + 沙箱镜像 | 无 Docker 时工具如实不可用；有 Docker 时真实执行/测试通过 |
| **5 前端** | 三视图 + markdown/高亮/复制 + 错误态 + 状态灯 | 全流程手测：登录→导入→对话→工具→停止→刷新恢复 |
| **6 测试与部署** | 单测/集成测试补齐；compose 生产形态；README 重写 | `docker compose up` 一键起；端到端验收通过；228+ 旧测试清理为新测试集 |

每个 Phase 结束必须全量测试通过，且不引入回归；测试文件与被测模块同生命周期（删功能=删测试）。
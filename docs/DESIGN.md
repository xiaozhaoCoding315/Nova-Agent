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

`ADMIN_USERNAME/ADMIN_PASSWORD/DEMO_USERNAME/DEMO_PASSWORD`、`DASHSCOPE_MODEL`（默认 `qwen3.8-max`）、`MAX_ROUNDS`、`LLM_TIMEOUT`、`DEMO_DAILY_TOKENS`、`DEMO_SANDBOX_DAILY`、`POSTGRES_DB=nova_agent`；删除 `NEO4J_*`。

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
---

## 15. v2.1 增量：可验证工程能力

> 目标：从"能聊代码"升级为"敢对结论负责、能算清影响、能交付验证过的补丁"。

### 15.1 证据化回答（Verification Layer）
- 回答结束后由后端校验文本中的 `文件:行号` 引用：存在性、后缀匹配、行号是否越界；无关联仓库时标记为"未校验"
- SSE 新增 `evidence` 事件；证据快照与 `tools_used` 一起写入 `messages.tool_json`，历史消息可回看
- 前端证据条：`N 处引用已核对 / 沙箱实测 / N 处引用可疑 / 未校验`，可展开逐条查看
- 系统提示词明确告知模型"引用会被逐一校验"，行为类结论必须沙箱实测

### 15.2 导入依赖图（影响雷达与项目大脑的底座）
- 索引时提取并解析导入：Python（ast，含相对导入）、JS/TS（相对路径 + 扩展名/index 解析）、Java/Kotlin/Scala（包路径后缀匹配）
- 存储 `file_deps(repo_id, file_id, source_path, target, resolved_path, kind)`，重建索引级联清理
- 未解析的外部依赖（如 `react`、`os`）不入图

### 15.3 变更影响雷达
- `impact_analysis` 工具 + `GET /repos/{id}/impact`：符号（精确优先）或文件路径 → 直接依赖、1-3 层传递依赖、符号引用（PG 词边界正则）、相关测试、风险评分与建议测试命令
- 风险规则：直接依赖数、传递依赖数、目标是否为类型/类、是否缺少相关测试
- 前端「工作区 → 影响分析」面板：风险卡片、依赖文件列表（可打开）、引用位置、建议命令可复制

### 15.4 项目大脑
- 索引完成后确定性生成（不调用 LLM）：语言分布、入口点、热点文件（入度）、推荐阅读顺序、模块统计、依赖图（Top 24 节点）、术语表
- 存储 `repos.brain JSONB`，`GET /repos/{id}/brain` 返回；前端「项目地图」以 SVG 环形依赖图 + 列表呈现，节点可点击打开文件

### 15.5 红-绿修复任务
- 数据表 `tasks(id, user_id, repo_id, title, bug_report, status, steps, result)`
- 流水线：检索相关文件 → LLM 生成 `{analysis, test_files, fix_files}`（关闭深度思考以控制时延）→
  沙箱带测试跑（必须失败=红）→ 带补丁复跑（必须通过=绿，最多一次修复迭代）→ 生成 unified diff
- 状态机：`running → ready | failed`；`ready → applied | rejected`
- **人工审批栅栏**：补丁只写入任务结果，`POST /tasks/{id}/apply` 才落盘并自动重建索引
- 沙箱配额与审计复用 `run_code` 的配额规则（每次运行均记录 `sandbox_run`）
- 前端「任务」视图：新建任务、步骤时间线（定位/生成/红/绿）、根因分析、diff、真实测试输出、批准/拒绝

### 15.6 新增接口
`GET /repos/{id}/brain` · `GET /repos/{id}/impact?q=` · `POST /tasks` · `GET /tasks` · `GET /tasks/{id}` · `POST /tasks/{id}/apply` · `POST /tasks/{id}/reject`

### 15.7 验证记录（2026-10-23）
- 示例仓库 `buggy_shop`：折扣 >100% 导致负总价 → 红阶段 `2 failed` → 绿阶段 `2 passed` → 审批写入 + 重建索引
- `calculate_tax` 影响分析：直接依赖 2（`app/main.py`、`tests/test_tax.py`），引用 3 处，建议命令 `pytest tests/test_tax.py`
- 证据化回答：6 处引用全部核对通过；沙箱实测标记在 run_code 成功时出现

---

## 16. v2.2 增量：Builder 模式（从 0→1）

> MVP 范围（已确认）：Plan 模式 + 文件提案审批；技术栈限定 Python 后端。

### 16.1 数据模型
`repos` 表新增：`kind`（import | builder）、`brief`（需求原文）、`rules`（项目约定，写入 AGENTS.md）、`plan JSONB`、`proposal JSONB`。
Builder 项目复用仓库工作区、索引、证据、项目大脑与影响分析。

### 16.2 状态机与审批栅栏
`planning → plan_ready →（确认）→ approved →（生成）→ generating → review →（批准）→ indexing → ready`
- 失败回到 `failed` / `approved`，错误落 `repos.error`
- 任何文件写入都必须经过 `proposal/approve`；方案与代码各有一个确认点

### 16.3 生成策略
- 方案：LLM 输出结构化 JSON（summary/stack/structure/data_model/api/milestones/risks），后端裁剪字段与数量
- 文件：LLM 输出 `{files:[{path,content}], notes}`，后端做路径安全（拒绝对路径/穿越）、数量（≤30）与体积（单文件 ≤120KB、总计 ≤400KB）限制
- 结构化调用复用 `core/llm/json_call.py`：关闭深度思考（qwen3.8-max 开启思考时首 token 约 126s，关闭后约 9s），失败时重试一次 JSON 解析
- 写入后调用现有索引管线（符号/分块/向量/依赖图/项目大脑）并进入 `ready`

### 16.4 接口
`POST /repos/builder` · `GET /repos/{id}/plan` · `POST /repos/{id}/plan/approve` · `POST /repos/{id}/plan/generate` ·
`POST /repos/{id}/generate` · `GET /repos/{id}/proposal` · `POST /repos/{id}/proposal/approve` · `POST /repos/{id}/proposal/reject`

### 16.5 前端
工作区新增「新建项目」与「项目构建」页签：四阶段进度（方案→生成代码→审阅提案→写入项目）、方案可视化（结构/API/数据模型/里程碑/风险）、提案逐文件展开、退回重做可携带审阅意见。

### 16.6 验证记录（2026-10-23）
- 输入「待办清单 API」需求 → 方案含 5 个端点、4 个里程碑、4 条风险 → 确认后生成 12 个文件（app/tests/README/AGENTS.md 等）→ 批准写入 → 索引产出 11 文件 / 38 分块 / 25 符号 / 6 依赖
- 生成代码在沙箱中 `python -m compileall` 全部通过；随后对该项目提问「有哪些 API」→ 模型用 `nl -ba` 读取源码，给出 5 个端点与准确行号，证据校验通过
- 发现并修复：`run_code` 曾对整个仓库做风险正则扫描，README 中的 ```bash 代码块被误判为注入导致所有沙箱调用被拦截；现只扫描模型本轮新写的代码

### 16.7 已知边界
- 只生成 Python 后端；不安装依赖、不启动服务（沙箱禁网），深度运行验证依赖后续「构建沙箱」
- 生成质量受模型与需求描述影响；通过审批与证据机制降低风险，但不替代人工 review

---

## 17. v2.3 增量：对话内编辑 + 权限模式 + 快照

### 17.1 权限模式（per-session）
`readonly | ask | auto`（存 `sessions.permission_mode`，默认 `ask`）
- `readonly`：注册表直接拦截 `write`/`execute` 类工具（write_files、run_code），并给出明确提示
- `ask`：读/查/执行允许；`write_files` 只生成待审批提案，不落盘
- `auto`：`write_files` 直接写入（仍保留快照与审计）

### 17.2 新工具
`read_file`（分页读原文）、`list_files`（按前缀列文件）、`write_files`（整文件写入；diff + 快照 + 审批）。
工具定义新增 `category` 字段（read/write/execute/network），权限判定集中在 `ToolRegistry.execute`。

### 17.3 编辑流水线与快照
`edits` 表：`files`（新内容）、`base_files`（写入前快照，新增文件为 null）、`diff`、`status`、`session_id`。
- 提案：`POST /chat/message` 中 `write_files` 在 ask 模式生成 `edit_proposal` SSE 事件 + `edits` 记录
- 批准：写入文件 → 状态 `applied` → 后台 `reindex_repo`
- 拒绝：状态 `rejected`，不落盘
- 撤销：用 `base_files` 恢复（新增文件删除）→ `reverted` → 重建索引
- 历史消息保存 `tool_json.edits`，前端 `EditCard` 可在历史会话中继续批准/撤销

### 17.4 前端
对话仓库栏新增权限模式选择（只读 / 确认写入 / 自动执行）；编辑提案卡片展示文件列表、可展开 diff、批准/拒绝/撤销与状态。

### 17.5 验证记录（2026-10-23）
- ask 模式：模型 `read_file` → `write_files`（2 个文件）→ 生成 diff 提案；磁盘未变；UI 点击批准后落盘并重建索引；点击撤销后文件恢复原文（状态 reverted）
- readonly 模式：`write_files` 与 `run_code` 均被拦截，模型如实说明并建议切换模式
- 修复：编辑后误用增量 `index_repo` 导致索引重复（11 文件变 33 条），已改为清空重建的 `reindex_repo`，现场重建后恢复 11 文件 / 25 符号

---

## 18. v2.4 增量：构建验证沙箱

### 18.1 镜像与依赖
- `nova-builder`：python:3.12 + fastapi/uvicorn/pydantic/pytest/httpx/numpy，用于仓库级测试；`nova-sandbox` 保持轻量用于片段执行
- `run_code` 新增 `env` 参数（builder / slim）；带 `repo_id` 默认走 builder，共享仓库级依赖卷 `nova-deps-<repo>`（挂载 /deps，`PYTHONPATH=/deps:/workspace`）
- `install_deps`（管理员、`SANDBOX_ALLOW_NETWORK=true`）：固定命令 `pip install --target /deps -r requirements.txt`，root 在沙箱内安装，产物持久化到依赖卷；其余运行仍以非 root、只读根文件系统执行

### 18.2 一键验证
`POST /repos/{id}/verify`：把仓库文件复制进沙箱，用 builder 镜像跑 `python -m pytest -q`，结果（status/exit/stdout/image/时间）写入 `repos.last_check`；前端工作区对任何就绪仓库提供「验证」按钮，Builder 完成后同样适用。

### 18.3 验证记录（2026-10-23）
- `todo-api` 首次验证：**9 failed / 1 passed**（SQLite 跨线程使用，生成代码的真实缺陷）
- 让 Nova 在对话中复现并修复：定位 `conftest.py` 的 `check_same_thread` 与 TestClient 线程池问题，写入修复 → 再次验证 **10 passed**
- 依赖卷自测：联网安装 `cowsay==6.1` 到 `nova-deps-selftest`，随后离线运行 `import cowsay` 成功

### 18.4 安全边界
- 联网仅限管理员显式开启；命令固定为 pip 安装，不接受任意命令
- 安装进程在沙箱容器内以 root 运行（pip 需要写依赖卷），仍受禁宿主挂载、pids/内存/CPU 限制约束
- 依赖卷按仓库隔离；删除仓库时不自动删除卷（可在服务器上手动清理）

---

## 19. v2.5 增量：桌面 Agent 形态前端

参考 Claude Code / Codex / Cursor 的桌面 Agent 布局：
- **左侧图标导航栏**：对话 / 工作区 / 任务 / 设置 + 用户与退出
- **顶栏**：当前视图、命令面板入口、真实健康状态
- **底部状态栏**：当前模型（qwen3.8-max）、权限模式、沙箱可用性、今日 token、版本
- **命令面板**：Ctrl/⌘ + K，支持搜索并执行「切换视图 / 新建对话 / 切换权限模式 / 退出」
- **快捷键**：Ctrl/⌘ + 1..5 切换视图（对话/工作区/变更/任务/设置）；Esc 关闭面板
- 工作区顶栏新增「验证」按钮与结果条（通过/失败、exit code、镜像、时间，可展开输出）

---

## 20. v2.6 增量：Git 交付 + Trajectory + Headless CLI

### 20.1 Git 交付
- `core/git_ops/service.py`：`init/commit/status/diff/rollback/export_zip`，全部用 `git -C <workspace>` 固定参数调用（超时、禁用 shell）
- 工作区初始化后：对话编辑批准/撤销、红-绿任务应用、Builder 写入都会**自动提交**（`auto_commit`，失败不影响主流程）
- 回滚：`git reset --hard <hash>`（前端二次确认）→ 后台 `reindex_repo`
- 导出：zip 排除 `.git`/构建目录，临时文件下载后清理；单文件 >5MB 跳过
- API：`GET /repos/{id}/git`、`POST /git/init|commit|rollback`、`GET /git/diff`、`GET /repos/{id}/export`
- 前端「Git 交付」页签：分支/干净状态、diff、提交框、历史提交（回滚需确认）、导出按钮

### 20.2 Trajectory（全链路轨迹）
- 表 `trace_events(session_id, turn_id, kind, payload, created_at)`
- 记录：`user`、`turn_start`（含权限模式与仓库）、`retrieval`（命中路径）、`llm_round`（轮次/字符/真实 token）、`tool_call`、`tool_result`、`edit_proposal`、`edit_applied/rejected/reverted`、`error`、`done`（最终回答、工具、耗时）
- 写入 best-effort，失败不阻塞主链路；`GET /chat/sessions/{id}/trajectory`
- 前端「轨迹」抽屉：按时间线展示、可展开查看原始 payload

### 20.3 Headless CLI
- `backend/nova.py`：`repos / run / verify / trajectory / export`
- `run --json` 输出 JSONL 事件；默认 `--permission readonly`；退出码 0 成功 / 1 失败 / 2 请求错误
- 通过 HTTP + 登录 Cookie 与 Web 服务共用同一套权限与审计（CI 可复现）

### 20.4 验证记录（2026-10-23）
- Git：init → 修改 README → 检测 dirty/diff → commit（`test: git delivery flow`）→ 回滚到首个快照（改动消失、索引重建）→ 导出 zip（12 文件，不含 .git）
- 轨迹：一轮只读问答产生 5 个事件（user/turn_start/retrieval/llm_round/done），UI 抽屉展示正常
- CLI：`verify`（passed/exit 0）、`trajectory`（5 事件）、`export`（12 文件）、`run --json`（29 个事件，含 tool_call/tool_result/evidence）

---

## 21. v2.7 增量：P0 安全与配额加固（2026-10-23）

### 21.1 路径与密钥防护
- 新增 `core/security/paths.py`：统一 `normalize_relpath` / `is_secret_path` / `resolve_repo_path`
- 拒绝绝对路径、`..` 穿越、同前缀兄弟目录、符号链接逃逸；`.env*`（示例文件除外）、`.git/`、私钥与凭据文件禁止读写
- 接入 `read_file`、对话编辑（创建/批准/快照）、红绿任务应用、Builder 应用、文件查看 API、`run_code` 仓库复制、`install_deps`

### 21.2 测试完整性守卫
- 新增 `core/security/test_guard.py`
- 修改已有测试文件时，删除测试函数或新增 `skip`/`skipTest` 标记会被拒绝
- 红绿任务必须是新测试文件，不能覆盖已有测试；在编辑创建、批准、任务应用、Builder 应用四个入口统一校验

### 21.3 配额与用量覆盖
- `usage_log` 增加 `source`（chat / task / builder / memory）；新增 `core/llm/usage.py` 统一记账
- 新增 `ensure_token_budget`：对话逐轮、任务每次生成、Builder 每次生成、记忆抽取前都检查每日 token 预算
- 新增 `check_job_quota`：导入 / 重建索引 / 红绿任务 / Builder 每小时次数；`check_search_quota` 限制仓库搜索
- `/verify` 复用沙箱日配额；编辑批准、任务应用、Builder 写入、Git 回滚触发的重建索引也计入配额
- 配置项：`ADMIN_JOB_HOURLY` / `DEMO_JOB_HOURLY`

### 21.4 会话关联仓库与项目规则
- `sessions.repo_ids` 持久化关联仓库；`POST /chat/message` 校验仓库归属（防跨用户检索），前端切换会话时恢复/清空选择
- 新增 `core/agent/rules.py`：读取关联仓库根目录 `AGENTS.md`（兼容 `CLAUDE.md`），Builder 项目回退到 `repos.rules`，注入系统提示词并限制总长度

### 21.5 验证记录（2026-10-23）
- 后端 `python -m pytest tests -q`：**141 passed**
- 前端 `npm run build`（tsc + vite）：通过
- 新增测试：路径/密钥、测试守卫、项目规则、配额记账

---

## 22. v2.8 增量：P1 验证闭环与只读审查（2026-10-23）

### 22.1 栈感知验证 profile
- 新增 `core/verify/profiles.py`：检测 Python/Node 项目；Python 默认执行 `compileall` + `pytest`，有 `ruff.toml`/`mypy.ini` 时追加可选 lint/类型检查
- 新增 `core/verify/service.py`：逐步运行、逐项记录命令/退出码/输出/耗时；必需步骤失败后停止，返回结构化 `steps` 与 `stack`
- `/repos/{id}/verify` 改为调用统一服务；Node/前端项目返回 `unsupported`，不伪装通过
- `Dockerfile.builder` 增加 ruff / mypy

### 22.2 红绿任务升级
- 红阶段分类：只有测试真实运行并失败才算有效红；`ERROR collecting`、`ModuleNotFoundError`、`ImportError`、`SyntaxError`、0 收集、超时均判定为无效复现
- 绿阶段从“只跑新测试”改为 **全量 `compileall + pytest`**；失败最多自动修复 **3 次**
- 任务结果保存 `base_files` 快照，应用前检测文件是否被外部修改

### 22.3 文件冲突检测
- 新增 `core/conflicts.py` 的 `ConflictError`
- 对话编辑：创建时保存 base 快照；批准时对比当前内容，冲突返回 409；撤销时检测应用后是否又被修改
- 红绿任务与 Builder：生成时保存 base 快照，应用前比对；冲突均返回 409，不再静默覆盖

### 22.4 只读 Reviewer
- 新增 `core/review/service.py`：直接 LLM 调用且不提供任何工具，结构上无法写入/执行
- 输出 `verdict`（pass/warn/block）、summary、blocking/non-blocking（文件/行号/建议）、evidence
- 支持 `POST /edits/{id}/review` 与 `POST /tasks/{id}/review`；编辑审查结果落 `edits.review`，任务审查结果写回 `tasks.result.review`
- 前端 `ReviewPanel`：编辑卡片与任务详情均可触发审查并展示结论

### 22.5 交付报告
- 新增 `core/agent/report.py`：确定性生成，不调用 LLM
- 内容：状态、执行命令与退出码、改动文件、测试/引用检查、未验证项、错误、token/耗时/轮次
- `done` SSE 事件携带 `report`；同时写入 `messages.tool_json.report`，历史消息可回看
- 前端 `DeliveryReport` 组件：折叠展示检查结果、命令、改动文件与未验证项

### 22.6 验证记录（2026-10-23）
- 后端 `python -m pytest tests -q`：**161 passed**
- 前端 `npm run build`：通过
- 真实验证：`todo-api` 仓库在 `nova-builder` 中执行语法检查 + pytest，**10 passed**，返回 2 个结构化步骤
- Reviewer 冒烟：对一条 Todo API diff 调用真实模型，读取项目 `AGENTS.md` 后给出 `block`，指出响应格式、sqlite3 使用和缺少测试三处违约
- UI 冒烟：在生产形态页面验证交付报告、只读审查面板、会话关联仓库恢复；真实审查接口返回 `block` 并渲染 blocking 依据
- 修复回归：P0 中若干入口把同步的 `check_job_quota` 当成异步函数 `await`，导致审查接口 500；已全部修正并新增静态契约测试 `tests/test_api_contracts.py`
- 本地库迁移：`edits.review` 列已生效

### 22.7 已知边界
- 验证 profile 目前只执行 Python；Node/前端项目标记 `unsupported`（P2）
- Reviewer 是单次结构化审查，不是多智能体辩论，结论作为证据补充
- 冲突检测基于完整文件内容快照，适合当前整文件写入模型；后续若引入 patch，需要改为 hunk 级基线

---

## 23. v2.9 增量：P0 可靠性加固（2026-10-23）

### 23.1 持久任务队列
- `jobs` 表 + `JobRunner` 在 FastAPI lifespan 启停；使用 `FOR UPDATE SKIP LOCKED` 领取，支持心跳、取消、重试、优雅停机与崩溃恢复。
- 导入 / 重建索引 / 红-绿 / Builder 方案与文件生成 / 应用后重建索引全部改为入队，替换裸 `asyncio.create_task`。
- 新增 `/api/v1/jobs` 列表、详情、取消、重试接口。
- 取消请求立即返回；沙箱容器按 `nova.job_id` 标签在后台清理。
- 会话摘要作为 `session_summary` job 异步执行。

### 23.2 记忆修复
- facts 查重与写入改为 `(user_id, hash)`，修复跨用户碰撞与 `ON CONFLICT (hash)` 失效导致的静默写入失败。
- 新增 `core/memory/summary.py`：按 `summary_upto_id` 增量压缩，保留最近 8 条原文，摘要 ≤40 行 / 2000 字。
- Agent 系统提示词注入「早期会话摘要」，历史消息只取摘要点之后的增量。

### 23.3 验证记录
- 后端 `python -m pytest tests -q`：**173 passed**（新增 jobs/facts/summary 测试）。
- 前端 `npm run build`：通过。
- 真实队列冒烟：claim → cancel 接口 105ms、任务状态 261ms 内变为 `canceled`。
- 崩溃恢复冒烟：心跳过期的 `running` 任务在 Runner 启动后自动回队列并执行成功。
- 本地库迁移版本 1–3 已生效；`facts` 的 `(user_id, hash)` 唯一索引与 `ON CONFLICT` 已实测。

### 23.4 已知边界
- `/jobs` 尚未接入前端任务中心；当前任务页仍按 3s 轮询 `/tasks`（P1）。
- SPEC、ChangePlan、契约对齐、Node 验证仍未实现（P1/P2）。

---

## 24. v3.0 增量：P1 变更工作流（SPEC → 计划 → Gate → 审查 → 应用）

### 24.1 数据模型
- `change_requests`：`title / requirements / goal / in_scope / out_scope / interfaces / acceptance_cases / nfr / open_questions / status / version / proposal / evidence / job_id`。
- `change_tasks`：`seq / title / kind / in_scope / out_scope / acceptance / depends_on / status / attempts / result`。
- 状态机：`drafting → draft → approved → planning → plan_ready → plan_approved → executing → review → applied`，异常分支 `failed / canceled / rejected`。
- `docs` 迁移版本 4，空库与老库都能幂等升级。

### 24.2 SPEC 与 Planner
- `POST /changes`：异步 `change_spec` job 起草 SPEC；草稿可编辑；冻结前校验「目标 + 至少一条验收 + open_questions 清空」。
- `POST /changes/{id}/plan`：`change_plan` job 产出 2-8 个任务；服务端校验任务类型、验收长度、依赖只能指向更早任务（等价于无环），并保存 In/Out 范围。
- 任务模板：`feature / bugfix / refactor / test / docs / contract`，定义提示词与测试要求。

### 24.3 执行器与 Gate
- `change_execute` job 串行执行任务；每个任务的提示词包含 SPEC、任务 In/Out、模板提示、项目规则与相关文件完整内容。
- 生成文件必须通过路径安全、密钥拒绝、In/Out 范围、测试完整性守卫；越界或删测试会进入修复循环。
- Gate 在**未落盘**的 overrides 上运行：`run_verification(repo, user, overrides=...)`，因此验证的是最终提案而不是旧磁盘内容。
- Gate 失败只回喂失败摘要，单任务最多 3 次；`test` 类型任务允许“只跑回归、不改文件”。
- 全部任务通过后，汇总为**一个 `edits` 提案**（diff / 快照 / 冲突检测复用现有编辑服务），再做只读审查；审查 `block` 默认禁止应用。
- 应用后自动提交 Git、记录证据并触发重新索引。

### 24.4 前端
- 新增「变更中心」视图（Ctrl/⌘+5）：创建变更、编辑/冻结 SPEC、查看计划与验收、Job 进度/取消、Gate/审查/diff、批准应用/拒绝。
- SPEC 编辑只在草稿/失败状态启用；运行中轮询详情，草稿状态不做自动轮询，避免覆盖用户输入。

### 24.5 验证记录（2026-10-23）
- 真实模型在 `todo-api` 上执行「新增 GET /todos/stats + 测试」：
  - SPEC 自动起草，验收用例 4 条，open_questions 为空；
  - Planner 产出 5 个任务（Schema → 路由 → 测试 → 回归验证 → 文档），依赖串行；
  - 5 个任务全部 Gate passed，耗时 101.7 秒；
  - 只读审查 `pass`，统一提案 4 个文件、78 行 diff；
  - 应用后磁盘验证 passed（语法 + 单元测试），撤销后再次验证 passed。
- 后端 `pytest`：**183 passed**；前端 `npm run build`：通过（526.88 KB，chunk 警告仍在）。

### 24.6 已知边界
- 执行器生成完整文件而非 patch，超大文件/大改动可能受单任务 120KB、最终 300KB 限制。
- 变更 Gate 仍只支持 Python；Node/前端会标记 `unsupported` 并进入未验证项。
- 任务串行执行，未引入每任务分支/worktree；失败重试会重置任务状态并重新执行整条计划。
- 契约对齐与 Node 执行仍属于 P2。

---

## 25. v3.1 增量：P2.1 契约基础设施

### 25.1 关键 API 响应模型
- 为 changes / jobs / tasks / builder / git / edits / verify / trajectory / search / impact / brain 增加 Pydantic 响应模型与 `response_model`。
- OpenAPI schema 从 **22 个**增至 **65 个**；60 条路径全部保留。
- 修复 `builder.router` 被 include 两次导致的重复 operation ID，生成 OpenAPI 时 **0 警告**。
- `last_verify` 在无历史结果时返回 `null`，前端仍按“无结果”处理。

### 25.2 契约源与生成
- `backend/scripts/export_openapi.py`：从 `app.openapi()` 稳定导出 `contracts/openapi.json`；`--check` 比较快照。
- `frontend/scripts/contract-check.mjs`：先检查后端契约快照，再用 `openapi-typescript` 生成临时 TS 并与 `src/lib/api-schema.d.ts` 比较。
- npm 脚本：`contract:generate` / `contract:check`。
- `tests/test_contract.py`：快照一致 + 关键端点必须存在 JSON response schema。

### 25.3 验证记录（2026-10-23）
- 后端 `pytest`：**186 passed**。
- 前端 `npm run build`：通过（527.10 KB，chunk 警告仍在）。
- `npm run contract:check`：通过；手动注入一行漂移后退出码 1，恢复后通过。
- 使用 TestClient + 真实库验证 changes/jobs/tasks/git/verify/search/impact/brain/edits/trajectory 均返回 200，`ChangeOut` 的 proposal/review/tasks 字段完整。

### 25.4 已知边界
- 前端尚未全面改为引用 `components["schemas"]`，当前保留手写类型别名；逐域迁移在 P2.2/P2.3。
- OpenAPI 中的 `dict` 字段仍会生成较宽松的 TS 类型（如 change proposal 的 `tasks`）。
- 契约 Gate 已在 v3.4 接入；Node 沙箱在 v3.3 完成。

---

## 26. v3.2 增量：桌面 Agent 风格界面重构

### 26.1 布局
- 采用持久左侧栏（Coding Agent 常见结构）：品牌、五个主导航、会话历史、账号区。
- 会话列表支持搜索、按「今天/昨天/近 7 天/更早」分组、消息数与相对时间。
- 会话操作从「悬停垃圾桶 + 行内确认」改为「更多菜单 → 重命名/删除 → 删除确认弹窗」，避免误删与布局跳动。
- 新增 `PATCH /chat/sessions/{id}` 重命名接口；前端会话 store 同步更新。
- 聊天区新增会话标题行、上下文 chips、可折叠引用面板；消息增加 Nova 头像与助手/用户分层气泡。
- 移动端侧栏改为抽屉（Ctrl/⌘+B 或菜单按钮切换），Composer 增加输入提示。
- 全局样式补充深色 `color-scheme`、focus-visible、selection 与更细滚动条。

### 26.2 验证记录（2026-10-23）
- 前端 `npm run build`：通过（535.43 KB，chunk 警告仍在）。
- 浏览器结构验证：侧栏、搜索、会话分组、更多菜单、删除确认弹窗、重命名输入均存在；实际重命名后已恢复原标题，删除仅验证取消路径。
- 内嵌浏览器隐藏视口导致截图不可用，使用无障碍树 + DOM 文本断言验证；桌面端引用面板需在可见视口确认。

---

## 27. v3.3 增量：P2.2 Node 沙箱与多栈验证

### 27.1 Node 沙箱
- 新增 `Dockerfile.node-builder`：Node 20 + 全局 `tsc`，Compose 新增 `node-image` → `nova-node:latest`。
- `sandbox_status` 上报 `node_available` / `node_image`；Docker 不可用时如实标记。
- `sandbox/runtime.execute` 支持 `deps_mount`：Python 依赖卷挂载 `/deps`，Node 依赖卷挂载 `/workspace/node_modules`；联网安装使用 npm 镜像并设置 `/tmp` 缓存。
- `run_code` 新增 `env=node`（默认命令 `node main.js`）。
- `install_deps` 支持 `kind=node`：读取根目录 `package.json` + npm/pnpm/yarn lockfile，安装到 `nova-node-deps-<repo>` 卷（管理员 + 联网开关）。

### 27.2 多栈 Profile
- `VerifyStep` 增加 `image`、`deps_kind`、`network`；`run_verification` 按步骤选择 builder/node 镜像与依赖卷。
- Python 步骤保持 compileall / pytest / 可选 ruff / mypy；Node 步骤按 package.json 生成 install / lint / tsc / test / build。
- 混合仓库返回 `stack=fullstack`，Python 与 Node 步骤串行执行。
- 依赖安装步骤标记为非必需；未缓存且无网络时明确失败/跳过，不伪装通过。

### 27.3 验证记录（2026-10-23）
- 后端 `pytest`：**192 passed**；前端构建通过。
- `nova-node:latest` 构建成功（Node 20 + tsc）。
- 真实 Node 样例（node:test + tsc + 自定义 lint/build）验证：4 个步骤全部 passed。
- 注入失败测试后：`Node 测试` failed（exit 1），后续 build 停止，整体 `failed`；恢复后重新 passed。
- 样例仓库与依赖卷已清理，不污染工作区。

### 27.4 已知边界
- Node 依赖安装只支持仓库根目录 `package.json`；monorepo 子包、workspace 多包待扩展。
- `nova-node` 已预装 `tsc` 与 `openapi-typescript`；契约比较用 Node 脚本，不依赖 diffutils。
- `/repos/{id}/verify` 已改为后台 Job；长步骤之间的取消生效，单个 Docker 步骤内取消依赖容器清理。
- 变更执行器已自动复用 Node Gate 与契约步骤，但尚未用真实混合仓库跑完整变更。

---

## 28. v3.4 增量：P2.3 verify Job + 目标仓库契约 Gate

### 28.1 验证后台化
- 新增 `verify` Job handler：加载仓库与用户、运行 `run_verification`、写入 `repos.last_check`；验证失败时 Job 失败但证据仍落库。
- `POST /repos/{id}/verify` 改为入队并返回 `{ok, job_id}`；`GET /repos/{id}/verify` 返回上次结果。
- 工作区验证按钮轮询 `/jobs/{id}`，显示进度、步骤与取消；完成后自动刷新结果与契约面板。

### 28.2 契约 Gate
- 新增 `core/contracts/service.py`：
  - 自动发现 `contracts/openapi.yaml|yml|json`、根目录 `openapi.*`；
  - 支持 `nova.yaml` 覆盖 `contract.source` / `contract.target`；
  - 默认 target：`frontend/src/lib/api-schema.d.ts`、`web/src/lib/api-schema.d.ts`、`src/lib/api-schema.d.ts`。
- Node 镜像内执行 `openapi-typescript <source> -o /tmp/nova-contract.d.ts`，再用 Node 脚本与 committed target 逐字节比较；漂移输出 `contract drift` 并退出 1。
- 契约步骤作为 Profile 的必需步骤加入；没有契约源时明确跳过，不伪装通过。
- `GET /repos/{id}/contract` 返回 source/target、文件存在性与最近检查结果；工作区新增「契约」页签。

### 28.3 验证记录（2026-10-23）
- 后端 `pytest`：**200 passed**；前端构建通过；`contract:check` 通过。
- 真实契约样例：`contracts/openapi.json` + committed `frontend/src/lib/api-schema.d.ts` → 契约检查 passed。
- 手动追加一行 target 漂移 → 契约检查 failed（exit 1，输出含 `contract drift`）；恢复后重新 passed。
- verify Job 端到端：入队 → `succeeded` → `repos.last_check` 写入 `contracts/openapi.json → api-schema.d.ts` 的 passed 步骤。
- 浏览器验证工作区「契约」页签：source/target、最近检查与 `contract ok` 输出均正常；验证按钮显示进度并最终「验证通过」。

### 28.4 已知边界
- Gate 只读取已提交的契约与 target，不自动从运行中的 FastAPI 导出；契约刷新属于开发者/CI 动作。
- 契约源与 target 必须在仓库内；monorepo 子包仍按根目录处理。
- 前端契约面板是只读状态展示；从面板生成 target 的写操作尚未提供。
- 真实混合 Python + Node 变更任务尚未端到端回归。

---

## 29. v3.5 增量：P2.4 CI + 黄金仓库 + 变更分支

### 29.1 CI 与本地检查
- 新增 `.github/workflows/ci.yml`：Python 3.12 + Node 20，执行 `ruff check app`、`pytest`、前端构建、`contract:check`。
- 新增 `scripts/check.sh`：本地一键执行相同检查。
- 清理后端全量 lint（未使用导入与 `app.db` 显式 re-export），`ruff check app` 全绿。

### 29.2 黄金仓库回归
- `samples/python-api`：compileall + pytest。
- `samples/node-app`：lint + tsc + node test + build。
- `samples/fullstack-contract`：Python + Node + OpenAPI → TS 契约检查；`nova.yaml` 指定 source/target。
- `backend/scripts/run_golden.py`：创建临时仓库行、逐套运行 `run_verification`、比对期望状态、清理仓库行与 Node 依赖卷。
- 2026-10-23 实测：三套全部 passed；fullstack 6 步（语法/单测/lint/Node test/build/契约检查）。

### 29.3 变更分支交付
- 新增 `prepare_change_branch` / `restore_change_branch`：
  - 工作区有未提交改动时拒绝应用（409），避免与用户改动混合；
  - 从当前 HEAD 创建/切换到 `nova/change-<id8>`；
  - 应用失败时丢弃半成品并切回原分支；
  - 成功后证据记录分支名，工作区停留在变更分支，合并回主分支由用户手动完成。
- 前端交付证据展示分支；Git 面板可直接查看当前分支。

### 29.4 验证记录（2026-10-23）
- 后端 `pytest`：**202 passed**；`ruff check app` 通过。
- `scripts/check.sh` 通过：ruff + pytest + 前端构建 + 契约检查。
- 黄金仓库回归：`python -m scripts.run_golden` → all golden cases passed。
- Git 分支单测：隔离提交、切回原分支、脏工作区拒绝均通过。

### 29.5 已知边界
- 当前是“每变更一个分支”，不是每任务 worktree；多个变更会从当前分支继续叠加。
- 不自动合并/开 PR；用户需手动 review 后合并。
- 黄金仓库回归依赖本机 PostgreSQL 与 Docker 镜像，未放入 GitHub CI。
- CI 不构建沙箱镜像；`nova-node` / `nova-builder` 由部署或本地构建提供。

---

## 30. v3.6 增量：P3.1 三层记忆 + 交付指标

### 30.1 三层记忆
- **原始层**：`messages` 保留完整对话。
- **压缩层**：会话滚动摘要（每 20 条）+ 日摘要（`memory_daily`，每天一份，≤40 行）。
- **长期层**：`facts` 保存偏好/事实，`fact_days` 记录事实出现的日期；同一事实在 ≥2 个不同日期出现后自动晋升（`promoted_at`），重要性 +0.3。
- 事实召回从“仅按重要性”改为“语义相关度 0.7 + 重要性 0.3”混合排序；Embedding 不可用时回退为重要性排序。
- 维护循环每小时执行：事实衰减/TTL、事实晋升、昨日日摘要（不足 8 条消息跳过；已有摘要不重复生成）。
- 新增 `GET /memory`、`DELETE /memory/facts/{id}`、`DELETE /memory/daily/{day}`；设置页可查看/删除事实与日摘要。

### 30.2 交付指标
- `GET /status/metrics?days=7|30` 聚合：
  - 接受变更数 / 变更总数
  - 首次 Gate 通过率（无需 repair 的任务占比）
  - 返工率（`repair_attempts > 0` 的任务占比）
  - 审批耗时（`edits.created_at → applied_at` 平均值）
  - 窗口内 token 总量
  - 后台 Job 完成耗时 p95
- 设置页展示指标卡片，可切换 7/30 天窗口。

### 30.3 验证记录（2026-10-23）
- 后端 `pytest`：**209 passed**；`ruff check app` 通过；前端构建通过；`contract:check` 通过。
- 真实记忆链路：临时用户 10 条昨日消息 → 日摘要写入（159 字）；事实跨 2 天晋升（importance 1.3）；语义召回命中。
- 设置页浏览器验证：交付指标、记忆空态/列表、7/30 天切换入口均正常渲染。

### 30.4 已知边界
- 矛盾事实检测尚未自动化；目前依赖同一事实 hash/语义去重与重要性衰减。
- 日摘要依赖 LLM，维护循环可能产生额外 token 成本；不足 8 条消息不生成。
- 指标为窗口内聚合，审批耗时只统计已应用的编辑；p95 统计全部后台 Job。
- 尚无周报导出与指标趋势图。

---

## 31. v3.7 增量：P3.2 能力权限 + Hooks + 密钥脱敏

### 31.1 能力策略
- `ToolDefinition` 增加 `capabilities`；未显式声明时按工具名/类别映射到：
  `fs.read / fs.write / proc.exec / net.fetch / git.write / deploy / secrets.read`。
- `decide_tool` 在工具执行前返回 allow/deny + 原因：
  - `readonly` 硬拦截 `fs.write / proc.exec / git.write / deploy`；
  - 路径统一 normalize，拒绝绝对路径、穿越与 `.env`/私钥/凭据；
  - `fetch_url` 受 `ENABLE_FETCH_URL` 控制；
  - `install_deps` 仅管理员且要求 `SANDBOX_ALLOW_NETWORK`；
  - `run_code` 拒绝危险模式与 `git push` / `git reset --hard` / `terraform apply` / `kubectl apply|delete`。
- 每次决策写入 `audit_log`（`policy_decision`），包含工具、能力、decision、args 摘要。

### 31.2 Hooks
- `TOOL_PRE_HOOK` / `TOOL_POST_HOOK` 由运维配置，模型无法修改。
- Hook 通过 stdin 接收 JSON（tool、capabilities、args、user、repo_ids、permission_mode；post 含 result），cwd 优先为关联仓库根目录。
- pre-hook 退出码 2 阻断并把 stderr 返回给 Agent；缺失/超时/其他非零退出均 fail closed。
- post-hook 失败只记录日志，不改变工具结果。
- Hook 的 stdout/stderr 在返回前脱敏。

### 31.3 密钥脱敏
- 新增 `redaction.py`：识别 OpenAI/Ark/AWS/GitHub/Slack 风格 key、JWT、私钥块、环境变量赋值。
- 接入点：工具输出、工具错误、SSE `tool_call` 参数、轨迹 payload、审计 args 预览、交付报告中的命令与错误。
- 工具执行仍使用原始参数，仅在展示/持久化/回传模型前脱敏。

### 31.4 验证记录（2026-10-23）
- 后端 `pytest`：**222 passed**；`ruff check app` 通过；前端构建与契约检查通过。
- 真实工具注册表验证：只读写/执行、`.env` 读取、`git push`、`rm -rf /` 全部 deny，并写入 `policy_decision` 审计。
- Hook 单测：退出码 2 阻断、缺失命令 fail closed、post-hook 失败不影响结果。
- 脱敏单测：key/JWT/私钥/env 与环境变量嵌套对象、工具输出、轨迹 payload 均被替换。

### 31.5 已知边界
- 能力策略是应用层防线，最终隔离仍是 Docker 容器；未来 `git.write / deploy` 工具接入时需继续沿用同一策略。
- Hook 命令由运维配置，必须使用可信脚本；当前不提供 Hook 签名或沙箱执行。
- 脱敏是正则启发式，不覆盖所有自定义密钥格式；真正的 DLP 需外部系统。
- 尚未实现网络域名 allowlist 与命令参数级白名单（当前为 denylist + 沙箱禁网）。

---

## 32. v3.8 增量：P3.3 预览部署 + 幂等账本

### 32.1 数据模型（迁移 6）
- `external_actions`：`idempotency_key` 唯一，记录 action/target/status/request/response/error/finished_at。
- `deployments`：记录 repo、container、host_port、url、status、image、command、workspace_path、stopped_at。
- 状态：`starting → running → stopped`，失败为 `failed`。

### 32.2 部署流程
1. 管理员在「工作区 → 预览」点击部署；API 校验 quota 与管理员角色。
2. 读取仓库文件（跳过密钥/二进制/依赖目录），复制到临时工作区。
3. 通过 `nova.yaml` 的 `preview.command/health` 覆盖启动命令与健康路径；默认 `uvicorn app.main:app` + `/health`。
4. `docker run -d`：`nova-builder` 镜像、127.0.0.1 随机端口、只读根文件系统、cap-drop ALL、no-new-privileges、pids/内存/CPU 限制、非 root。
5. 轮询健康检查（最多 45s）；失败则抓取容器日志、删除容器与临时目录、写入失败记录。
6. 成功写入 `running + URL`，幂等账本标记 succeeded；前端展示可点击 URL。
7. 下线：`docker rm -f` + 删除临时目录 + 账本记录 teardown；重复下线幂等。

### 32.3 幂等
- 部署键：`<user>:deploy:<repo>:<git head>`；相同版本重复部署直接复用运行中的 deployment。
- 已停止后再次部署自动换新键；失败任务可重试；显式 `force` 生成新键。
- teardown 键：`<user>:teardown:<deployment_id>`，重复调用不重复操作。

### 32.4 前端
- 工作区新增「预览」页签：部署按钮、运行中 URL、容器/端口、下线按钮、部署历史与错误。
- 仅管理员可用；demo 账号会收到 403 并显示错误。
- 页面明确提示当前仅支持 Python/FastAPI。

### 32.5 验证记录（2026-10-23）
- 后端 `pytest`：**227 passed**；`ruff check app` 通过；前端构建与契约检查通过。
- 真实 `todo-api` 部署：容器启动、`GET /health` 返回 200、URL 可访问。
- 重复部署返回同一 deployment id 与 URL（幂等）。
- teardown 后容器从 `docker ps -a` 消失，部署状态变为 stopped。
- 浏览器验证工作区「预览」页签：部署按钮 → running URL → 下线成功。

### 32.6 已知边界
- 仅支持 Python/FastAPI；Node/全栈预览与 compose 部署未接入。
- 预览使用 bridge 网络以支持本地端口映射；未做域名反代/TTL 自动回收。
- 临时工作区在正常 teardown 时清理；进程崩溃后可能残留，需后续启动清理任务。
- 预览运行的是仓库代码，仍应只对可信仓库/管理员开放。

---

## 33. v3.9 增量：P3.4 MCP 外接工具

### 33.1 传输与生命周期
- `core/mcp/client.py` 实现最小 MCP stdio 客户端：JSON-RPC 2.0、换行分帧、initialize / notifications/initialized / tools/list / tools/call。
- Windows 的 SelectorEventLoop 不支持 asyncio 子进程，因此使用 `Popen + 读线程 + call_soon_threadsafe`，与现有 psycopg 事件循环兼容。
- 客户端支持请求超时、进程退出错误映射与关闭清理；stderr 写入日志。
- MCP server 在 FastAPI lifespan 启动时连接、关闭时终止；任一 server 失败不阻塞应用启动。

### 33.2 Allowlist 与能力
- `mcp_servers.json` / `MCP_SERVERS_JSON` 配置 server：command、args、enabled、allow_tools、capabilities、admin_only、timeout。
- 只有 `allow_tools` 与 `capabilities` 同时声明的工具才注册；工具名 `mcp__<server>__<tool>`。
- 每个 MCP 工具携带显式 capability（fs.read/fs.write/proc.exec/net.fetch/git.write/deploy/secrets.read），进入统一 policy；默认 `MCP_ADMIN_ONLY=true`。
- 工具 wrapper 再做一次管理员校验（纵深防御）；参数摘要与结果写入既有审计。

### 33.3 验证记录（2026-10-23）
- 后端 `pytest`：**230 passed**；`ruff check app` 通过；前端构建与契约检查通过。
- 使用 fake MCP server（真实 stdio JSON-RPC）验证：
  - initialize / tools/list / tools/call 成功；
  - allowlist 只暴露 `echo`，未声明的 `write_secret` 不注册；
  - 管理员调用返回 `echo: hello`；
  - demo 账号被能力策略拒绝。
- MCP client 在 Windows SelectorEventLoop 线程模型下运行通过。

### 33.4 已知边界
- 仅支持 stdio transport；HTTP/SSE、OAuth、资源订阅等 MCP 能力未接入。
- server 进程是运维可信代码；当前没有额外进程沙箱、签名或资源限制。
- 工具参数只经过通用路径/能力校验，未按 MCP server 语义做细粒度参数过滤。
- 工具发现发生在启动时；配置变更需重启应用。

---

## 34. v4.0 增量：P4.1 Node/全栈预览 + TTL 回收

### 34.1 多运行时预览
- `_preview_config` 自动选择运行时：
  - `app/main.py` → Python / `nova-builder` / `uvicorn` / 端口 8000 / `/health`
  - `package.json` 且有 start 脚本 → Node / `nova-node` / `npm start` / 端口 3000 / `/`
  - `nova.yaml` 的 `preview.runtime/command/port/health/image` 可覆盖，用于 fullstack 或自定义服务
- Python 预览挂载仓库依赖卷 `/deps`（PYTHONPATH）；Node 预览挂载 `nova-node-deps-<repo>` 到 `/workspace/node_modules`（只读），并注入 `PORT`。
- 端口映射按运行时端口动态设置；容器仍为只读根文件系统、cap-drop ALL、非 root、资源限制。

### 34.2 TTL 回收
- 新增 `PREVIEW_TTL_MINUTES`（默认 120，0 = 关闭）。
- 小时级维护循环调用 `cleanup_expired()`：找出超时的 `running` 部署，逐个执行 teardown（删容器、删临时目录、写 stopped、记账）。
- teardown 仍保留幂等键，重复清理不重复操作。

### 34.3 验证记录（2026-10-23）
- `samples/node-app` 真实部署：Node 容器启动，`/` 返回 200（`node preview ok`），teardown 清理。
- `samples/fullstack-contract` 通过 `nova.yaml preview.runtime=node` 覆盖，`/` 返回 200（`fullstack preview ok`）。
- Python `todo-api` 预览仍通过健康检查 200。
- 部署/TTL 单测覆盖 Python/Node 配置、端口校验、超时清理；后端测试见最新全量结果。

### 34.4 已知边界
- 域名反代/HTTPS 未自动配置；当前只返回 `127.0.0.1:<port>` 本地 URL。
- Node 依赖需预先安装到依赖卷；预览启动不会联网安装。
- TTL 清理依赖小时级维护循环，最坏延迟约 1 小时。
- 预览使用 bridge 网络以支持端口映射；未做网络域名 allowlist。
- 临时工作区在正常 teardown/TTL 清理时删除；进程崩溃仍可能残留。

---

## 35. v4.1 增量：P4.2 契约驱动 Builder（全栈）

### 35.1 模式与数据
- `repos.stack_mode`（迁移 7）：`python`（原行为）或 `fullstack`。
- `POST /repos/builder` 接受 `stack`；前端「新建项目」增加模板选择。
- 全栈计划要求单一契约源 `contracts/openapi.json`，后端 FastAPI 与前端类型都由它派生。

### 35.2 生成流程
1. Planner 生成全栈方案（契约、后端、双栈里程碑）。
2. 文件生成只要求 LLM 输出 OpenAPI 契约 + FastAPI 后端 + pytest + 文档，不生成前端。
3. 服务端校验契约（OpenAPI 3.x + paths），用 `nova-node` 的 `openapi-typescript` 生成 `frontend/src/lib/api-schema.d.ts`。
4. 确定性生成 TypeScript API Explorer：根 `package.json`/`tsconfig.json`、`frontend/src/endpoints.ts`（`satisfies keyof paths`）、`app.ts`、契约一致性测试、lint/build 脚本。
5. 追加确定性 `tests/test_contract.py`：校验契约中的 path/method 都在 FastAPI OpenAPI 中存在。
6. 在**未落盘**的 overrides 上运行 Python + Node + 契约 Gate；失败时把失败摘要与当前契约/后端回喂，最多修复 1 次。
7. 提案保存 Gate 证据与修复次数；Gate 未通过的提案禁止写入，需要退回重做。

### 35.3 验证记录（2026-10-23）
- 真实模型生成「任务清单 API」全栈项目：23 个文件；双栈 Gate **7 步全部 passed**（Python 语法/单测 + Node lint/tsc/test/build + 契约检查）。
- 将提案写入磁盘后再次运行验证：仍为 **passed**，stack=fullstack，image=mixed。
- 修复循环验证：一次 Gate 失败后自动回喂，最多 1 次；若仍失败则提案保持 review 且 apply 被阻止。
- 后端 `pytest`：**238 passed**；ruff 通过；前端构建与契约检查通过。

### 35.4 已知边界
- 全栈前端是**无框架 TypeScript API Explorer**（可离线构建），不是 React/Vite 脚手架；React/Vite 模板待后续。
- 生成质量受模型影响；Gate 失败后需要退回重做，当前只自动修复 1 次。
- 契约一致性测试只校验 path/method 存在，不校验字段级 schema；前端类型由契约生成，后端 Pydantic 字段由 Gate 测试间接保障。
- 全栈 Builder 依赖 `nova-builder` / `nova-node` 镜像；依赖安装不在生成阶段自动执行。
- 仍为“提案 → 批准 → 写入”，不会自动部署；预览需管理员手动触发。

---

## 36. v5.0 增量：P5.1 用户自带模型（BYOK）与桌面 Agent 界面

### 36.1 数据模型（迁移 8）
- `user_llm_settings(user_id PK, provider, base_url, model, api_key_enc, updated_at)`：每个用户一套活动配置，随用户级联删除。
- `sessions.model`：会话级模型覆盖；未设置时使用用户配置的默认模型。
- `LLM_ALLOW_SERVER_FALLBACK`：部署级开关。`false` 时未配置个人 Key 的用户无法调用模型，避免公开部署消耗服务端额度。

### 36.2 密钥与解析
- API Key 使用 `SECRET_KEY` 经 SHA-256 派生 Fernet 密钥加密；读取接口只返回 `has_key`、`key_hint`（后四位），原始 Key 不进入响应、轨迹或工具参数。
- 保存时 `api_key` 为空表示保留已存 Key，支持只改模型/服务商而不重输密钥；服务商、Base URL、模型均有校验，拒绝非 http(s) 与云元数据地址。
- `get_llm(user_id, model)` 解析顺序：用户配置优先且**独占**（错误时不会静默回退到服务端 Key）→ 服务端共享链（若允许）→ 明确报错。
- 对话、Builder、变更、Reviewer、记忆抽取与摘要等所有 `llm_json`/Agent 调用都携带 `user_id`，统一走同一解析逻辑。
- 会话模型写入 `sessions.model`，SSE `meta` 与 `SessionOut` 回传；前端 Composer 按会话切换并持久化。

### 36.3 API 与前端
- `GET/PUT/DELETE /settings/llm`：查看（含服务商预设与掩码）、保存、移除个人配置。
- `POST /settings/llm/test`：使用待保存或已保存配置做一次真实连通性测试。
- 设置页改为分区导航（模型与密钥 / 用量 / 指标 / 记忆 / 系统状态 / 账号）；模型页提供服务商卡片、Base URL、密钥、模型下拉与自定义模型。
- 应用外壳统一为桌面 Agent 风格：可折叠侧栏（Ctrl/⌘ B）、单一顶部栏、会话标题、模型来源徽标、底部状态栏；Composer 内置模型、权限、上下文与发送控件。
- 新增 `GET /settings/llm` 契约与前端类型；OpenAPI 快照与 `api-schema.d.ts` 同步更新。

### 36.4 验证记录（2026-10-24）
- 真实数据库迁移 8 幂等应用；临时用户验证加密存储（DB 中无明文）、`key_hint` 掩码、会话模型持久化、用户配置解析为 `OpenAICompatibleLLM`，清理后无孤儿配置/会话。
- API 端到端：GET 初始为 `server` → PUT 后为 `user`、掩码返回 → 不带 Key 的 PUT 保留密钥 → 会话发送后 `GET /chat/sessions` 返回所选模型 → DELETE 回到 `server`。
- 错误 Key 真实请求返回 401，SSE 如实上报「模型调用失败」，不泄漏密钥。
- 浏览器验证：设置页模型与密钥分区、保存反馈、个人/共享来源徽标、Composer 模型下拉与会话模型写入均正常；临时测试账号已删除。
- 后端 **245 passed**；ruff、前端构建、`contract:check` 全部通过。

### 36.5 已知边界
- 每个用户同时只保存一套服务商配置，不支持多 Key 轮换或多模型并行路由。
- Embedding 仍使用服务端 `DASHSCOPE_API_KEY`；个人 Key 不覆盖 RAG 向量化。
- 配额仍按角色固定，未提供按用户的额度/成本上限；BYOK 调用仍写入 `usage_log`。
- 仍无自助注册与密码重置；账号由部署者维护。
- 运行中后端需要重启才能加载新迁移/路由（本地 dev 已验证）。

---

## 37. v5.1 增量：P5.2 导航收敛与对话内工作区

### 37.1 信息架构
- 主导航从 5 项收敛为 **对话 / 工作流 / 设置**；工作区不再是平级入口，`workspace` 作为对话内的展开视图存在。
- 对话页采用三栏：会话侧栏 · 对话主区 · 右侧上下文 Dock。
- 右侧 Dock 含两个页签：**项目**（仓库上下文、文件树、快捷工作流）与 **引用**（检索命中）；Dock 可收起，移动端隐藏，通过对话头部的「打开完整工作区」进入。

### 37.2 项目面板
- `ProjectDock` 复用 `useRepos` 与 `FileTree`：
  - 点击仓库：加入/保持对话上下文，并设为当前浏览仓库；
  - 文件树点击文件：直接打开完整工作区并定位到该文件；
  - 快捷入口：新建项目、导入、变更工作流、修复任务。
- `WorkspaceView` 增加 `initialRepoId` / `initialPath` / `onClose`：从对话打开时预选仓库与文件，左侧提供返回对话按钮；完整工作区保留原有七类工具页签。
- 工作区标签栏改为可横向滚动 + 不换行，避免在 1440px 下被仓库列表与验证区挤压。

### 37.3 工作流说明
- `WorkflowsView` 合并原「变更」与「修复任务」：
  - 顶部两条分段页签与一句适用场景说明；
  - 明确「日常问答/小改动不需要工作流」；
  - 支持从项目面板带入仓库，变更/任务页面自动预选。
- `ChangesView` / `TasksView` 接受 `initialRepoId`；TasksView 删除重复的本地 DiffView，复用共享组件。

### 37.4 验证记录（2026-10-24）
- `npm run build` 通过；后端测试与契约检查在最终 `scripts/check.sh` 中复验。
- 用无头 Chrome 在 1440×900 下真实登录并验证：
  - 对话三栏布局、右侧项目面板、仓库勾选与文件树；
  - 工作流页签与说明；
  - 从项目面板点击 `main.py` → 完整工作区自动打开并定位文件；
  - 完整工作区标签栏不再换行。
- 窄屏（约 620px）下右侧 Dock 隐藏，头部与移动抽屉仍可用。

### 37.5 已知边界
- 右侧 Dock 宽度固定 380px，不支持拖拽调整；完整工作区仍保留独立的三层侧栏。
- 未做主题切换与国际化；移动端不展示项目 Dock，只保留完整工作区入口。

---

## 38. v6.0 增量：P6 多用户账号、项目历史与文件隔离

### 38.1 账号与开户
- `users` 增加 `display_name/status/is_guest/expires_at/token_version/password_updated_at/recovery_code_hash/last_login_at`（迁移 9）。
- `REGISTRATION_MODE=open|invite|closed`；注册返回一次性恢复码，密码重置后恢复码失效。
- 游客：`/auth/guest` 创建 24 小时临时账号，独立 user_id；小时级维护任务清理过期游客及其仓库、附件、向量、容器与用量。
- JWT 带 `token_version`；改密、管理员改状态/角色会递增版本，旧 token 立即失效。
- `APP_ENV=prod` 时弱 SECRET_KEY、默认 admin/demo 密码直接阻止启动。

### 38.2 项目化会话
- 新增 `session_repos(session_id, repo_id)` 与 `sessions.primary_repo_id`（迁移 10），从旧 JSONB `repo_ids` 回填。
- `GET /chat/sessions?repo_id=` 按项目过滤；新建对话继承侧栏当前项目；会话行显示所属项目。
- 仓库/客户端状态统一到 chat store：`selectedRepoIds`、`historyRepoId`、`attachments`。
- 删除仓库时 `session_repos` 级联清理，不再留下失效上下文。

### 38.3 用户文件与附件
- 仓库存储迁移为 `data/users/<uid>/repos/<repo_id>`；旧 `data/repos/<id>` 在启动时幂等迁移。
- `user_files`（迁移 11）：用户、项目、会话、文件名、MIME、大小、sha256、存储路径、purpose。
- 文件 API：上传（大小/配额/owner 校验）、列表、下载、删除；聊天最多 5 个附件。
- 消息持久化附件元数据；`read_uploaded_file` 工具只允许读取本轮附件，避免 Agent 遍历个人文件库。
- 设置页「文件与存储」提供上传、下载、删除和配额条。

### 38.4 隔离加固
- Qdrant payload 写入 `user_id`，启动时对已有 repo 做 payload 回填；检索必须带授权 repo_ids，未选仓库 fail-closed。
- `jobs` 幂等键改为 `(user_id, idempotency_key)`；`external_actions` 同样按用户唯一，ledger 读写全部带 user_id。
- 删除仓库：先停预览容器、删 `nova_preview_*` 工作区与 `nova-deps`/`nova-node-deps` 卷，再删 DB 与 Qdrant 点。
- 删除账号：清理用户目录、每个仓库的 Qdrant 点/容器/卷、`usage_log` 与审计，再级联删除 DB 行。
- 预览历史列表补 repo owner 校验。

### 38.5 管理员与轻量部署
- 管理员用户列表带会话/项目/文件/存储/token 汇总；支持建号、禁用、重置密码、删除。
- 游客与正式用户分别有消息、token、沙箱、Job、存储额度。
- 2C2G 建议：单 worker、1–2 个并发 Job、沙箱 256MB/0.5 CPU、镜像预构建、游客低额度、静态前端由 FastAPI 托管。

### 38.6 验证记录（2026-10-24）
- 真实 DB 迁移 9–12 幂等应用；旧仓库迁移到 `data/users/1/repos`，Qdrant payload 回填 `user_id=1`。
- 注册 → 资料 → 改密（旧 token 401）→ 恢复码重置 → 登录；游客创建、文件上传、文件库、管理员禁用/删除全部通过。
- 项目会话：创建带 repo 的会话、按项目过滤、跨用户附加仓库/读取会话均 404。
- 文件隔离：A 上传的文件 B 下载 404；管理员删除账号后用户目录消失。
- 幂等账本：同一 key 在两个用户下生成两条独立记录。
- 无头 Chrome 1440×900 验证登录/注册/游客/文件库界面。
- 后端 **268 passed**，ruff、前端构建、契约检查全绿。

### 38.7 已知边界
- 无邮箱验证/邮件找回；密码恢复依赖恢复码或管理员。
- 项目严格私有，不支持团队共享；账号角色仍只有 admin/demo。
- 注册/消息限流为进程内滑动窗口，单实例；多副本需迁移到 PG/Redis。
- 存储配额只统计用户上传文件，不计仓库索引副本。
- 2C2G 不适合多人同时跑 Docker 验证；公开互联网还需反代限流/验证码。

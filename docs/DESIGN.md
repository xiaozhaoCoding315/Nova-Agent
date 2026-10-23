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
- **快捷键**：Ctrl/⌘ + 1..4 切换视图；Esc 关闭面板
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

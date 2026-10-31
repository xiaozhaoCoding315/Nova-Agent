# Nova Agent 下一阶段完善计划

> 日期：2026-10-30  
> 代码基线：`main` @ `d62746c` + 本轮工作区改动（未提交）  
> 验证基线：后端 `502 passed / 7 skipped`；`ruff` 通过；前端构建与契约检查通过  
> 对照对象：Claude Code、OpenAI Codex CLI、Cursor、Cline / Roo Code、Aider、OpenHands、Gemini CLI  
> 原则：不重写、不做多智能体表演、先闭环再扩面；每一项都给出可验证证据与验收标准。

---

## 0.1 第二轮进展（2026-10-30 晚）

| 项目 | 状态 | 说明 |
|---|---|---|
| A1 auto/full 密钥收口 | ✅ | 只读命令全模式净化副本；写命令遮蔽密钥 + `.git/config` 脱敏 |
| A0 沙箱宿主路径映射 | ✅ | 容器内 `/app/data` 自动翻译为宿主机挂载路径，修复 compose 下 run_code/run_command |
| A2 旧索引清理 | ✅ | `scripts/purge_secret_chunks.py`（幂等，支持 dry-run） |
| A4 安全 E2E / smoke | ✅ | `scripts/security_e2e.py`、`scripts/sandbox_smoke.py`；待服务器执行 |
| A5 多 worker 心跳 | ✅ | `local_agent_heartbeats` 表 + 进程内快路径 |
| B1 计划/待办 | ✅ | `update_plan` 工具 + SSE plan + 持久化 + `PlanCard` |
| B2 流式/取消 | ✅ | `tool_output` SSE、Popen 流式、单工具取消端点 |
| B3 命令审批 | ✅ | ask 写命令暂停 → 内联批准/拒绝 → 继续执行 |
| B4 工具体验 | ✅ | 终端尾部、实时输出、复制、`@` 提及、PlanCard、语法高亮、文件跳转 |
| C1 增量索引 | ✅ | `content_hash` 文件级增删改、Qdrant 点清理、依赖重解析、`force` 全量 |
| D1 CI 镜像/smoke | ◐ | workflow 已加 GHCR 构建 + 容器 smoke；需在 GitHub 实跑验证权限 |
| D2 备份/恢复 | ✅ | `deploy/backup.sh` + `deploy/restore.sh`（需输入 RESTORE） |
| D3 工具级指标 | ✅ | `status/metrics` 新增 tool_metrics + 设置页工具健康表 |
| D4 原生 provider | ✅ | Anthropic 原生 tool use + prompt caching（含 BYOK 预设） |
| D6 前端分割 | ✅ | 路由 lazy + manualChunks，主 chunk 从 767KB 降到 ~53KB |
| D8 测试快速档 | ✅ | `NOVA_TEST_FAST=1` 全量 ~1.5 分钟 |
| C2 tree-sitter | ✅ | TS/Go/Java/Rust 语法树符号，失败回退正则 |
| D5 MCP HTTP | ◐ | streamable HTTP + 静态鉴权；OAuth 待补 |
| D7 桌面端 | ◐ | 可选自动更新（`NOVA_UPDATE_URL`）；签名/托盘/开机启动待做 |
| A3 HTTPS | ⏳ | 待你确认线上入口 |
| B5/C3/D5-OAuth/D7 | ⏳ | 子代理、任务引擎统一、MCP OAuth、桌面签名/托盘 |

---

## 0. 本轮已经完成（不要重复做）

| 项目 | 状态 | 关键落点 |
|---|---|---|
| readonly/ask 密钥读取边界 | ✅ | `run_command` 净化工作区副本 + token 扫描 + 索引/检索过滤 |
| `fetch_url` 模式门禁 + 域名 allowlist | ✅ | readonly/ask 拒绝；`FETCH_URL_ALLOWED_DOMAINS` |
| auto/full 编辑后重建索引 | ✅ | chat loop 检测 applied edit 后 `enqueue_index` |
| 轮内上下文压缩 | ✅ | `context_governor`，按 BYOK 真实窗口计算 |
| 停止生成时沙箱清理 | ✅ | `CancelledError` → `docker kill` |
| 只读工具并行 | ✅ | `parallel_safe` + `gather` 上限 4 |
| 工具集按模式/可用性裁剪 | ✅ | readonly 隐藏写/执行；本机离线隐藏 `local_*` |
| ZIP 导入自动 Git baseline | ✅ | `git init` + baseline commit + 密钥排除 |
| Git 导入保留历史 | ✅ | 不再删除 `.git` |
| Provider 工具能力标记 | ✅ | `supports_tools`，coding 回退拒绝退化 |

**仍需你确认的运维项**：线上 8000 端口是否直接暴露公网、Caddy profile 是否启用、`COOKIE_SECURE` 是否为 true（原方案 3.3）。

---

## 1. 当前能力矩阵与剩余差距

状态：✅ 对齐 / ◐ 部分 / ❌ 缺失

| 维度 | Nova 现状 | 剩余差距 | 优先级 |
|---|---|---|---|
| 密钥边界 | ◐ readonly/ask 已净化；auto/full 仍可间接读 | auto/full 的 `grep -r SECRET .` 等间接读取 | P0 |
| 旧索引迁移 | ◐ 检索层已过滤 | 旧 chunk 仍在 PG/Qdrant，需清理脚本 | P0 |
| 命令审批 | ❌ ask 只允许只读命令，写命令直接拒绝 | 缺少“待审批命令 → 批准执行”的交互 | P1 |
| 上下文治理 | ✅ 已有压缩 | 前端展示压缩次数/节省 token 可选 | P2 |
| 计划/待办 | ❌ 无 `update_plan` | chat 级计划卡与持久化 | P1 |
| 工具输出流式 | ❌ 只显示“正在执行” | stdout 流式、单工具取消 | P1 |
| 工具卡片 | ◐ edit 有 Diff 卡；其余通用 JSON | 终端/语法高亮/文件跳转/复制/重试 | P1 |
| `@` 文件提及 | ❌ 占位符暗示但未实现 | 输入框自动补全仓库路径 | P1 |
| 子代理 | ❌ 无 | 只读探索子代理（可选） | P2 |
| 增量索引 | ❌ 改一个文件全量重建 | 文件级 hash 增量 | P2 |
| 符号索引 | ◐ Python AST；其他正则 | TS/Go/Java/Rust tree-sitter | P2 |
| 任务引擎 | ◐ tasks/changes/builder/night 四套 | 共享 Run/Step/Gate/Repair 抽象 | P2 |
| CI/CD | ◐ 有 lint/test/build | 镜像预构建、容器 smoke、fake-LLM E2E | P1 |
| 备份 | ❌ 只有文档命令 | 定时备份 + 恢复演练 | P1 |
| 工具级观测 | ❌ 只有任务/变更级指标 | 成功率/p95/错误分类/token 成本 | P2 |
| 原生 Provider | ❌ 仅 OpenAI-compatible | Anthropic/Gemini + prompt caching | P2 |
| MCP | ◐ stdio + allowlist | HTTP/SSE、OAuth、annotations | P2 |
| 前端体积 | ◐ 767KB 单 chunk | 路由级 code-split | P2 |
| 桌面/本机执行器 | ◐ Electron 安装包 + CLI agent | 自动更新、签名、开机启动、图形确认 | P2 |

---

## 2. Phase A：安全收口与上线闭环（约 1 周）

### A1. auto/full 模式的密钥读取收口

**现象**

readonly/ask 已经使用净化副本，但 `auto`/`full` 下 `run_command` 仍挂载真实仓库 `:rw`。策略层只拦截显式密钥路径 token，因此：

```text
auto + run_command "grep -r SECRET ."   -> 可以读到 .env
auto + run_command "grep -r TOKEN src/" -> 可以读到源码里的硬编码密钥
```

**证据**

- `backend/app/core/security/policy.py`：只对显式 token 做 `is_secret_path` 判断。
- `backend/app/core/tools/run_command.py:67`：`isolated = permission_mode in ("readonly", "ask")`。
- 索引/RAG 已过滤，但 shell 是另一条路径。

**方案（推荐混合策略）**

1. **只读命令统一走净化副本**：无论什么模式，只要 `classify_command` 判定为 READONLY，就用 `sanitized_workspace=True` 的副本执行。`grep -r` / `cat` / `git diff` 都属于这一类，直接绕开密钥文件。
2. **写命令保留真实工作区，但遮蔽密钥文件**：对 `auto/full` 的 mutating 命令，在 `docker run` 时把工作区内 `is_secret_path` 命中的文件用空文件 bind-mount 覆盖（`.git/config` 做 URL 凭据脱敏），目录（`.ssh/.aws/.kube/.gnupg`）用空目录覆盖。这样写操作仍持久化，但命令看不到 `.env`。
3. 如果 bind-mount 在目标环境不稳定，退化为“写命令也使用净化副本 + 执行后同步回工作区”，但需处理删除/重命名语义，风险更高；优先做方案 2。

**验收**

- `auto` 下 `grep -r SECRET .`、`grep -r TOKEN src/` 结果为空；
- `auto` 下 `edit_file` 写入仍持久化；
- `git status/diff/log` 正常；
- 新增单测覆盖遮蔽清单生成；服务器 E2E 覆盖 auto 读取拒绝。

**工作量/风险**：2–3 天；Docker bind-mount 行为需在服务器验证，保留 `SANITIZED_SHELL=0` 回滚开关。

---

### A2. 旧索引密钥清理

**现象**

本轮只在索引与检索层加了过滤。部署前已经建立的索引里，`credentials.json` / `secrets.yaml` 的 chunk 仍留在 PostgreSQL 和 Qdrant；检索层过滤能兜底，但数据仍在。

**方案**

- 新增 `backend/scripts/purge_secret_chunks.py`：
  1. 扫描 `repo_files`，按 `is_secret_path` 找出命中行；
  2. 删除对应 `symbols` / `chunks`；
  3. 按 chunk 的 point id 删除 Qdrant 点；
  4. 删除 `repo_files` 行；
  5. 幂等，可重复执行。
- 部署文档增加“升级后执行一次”，或在 admin 设置页加“清理密钥索引”按钮。
- 新索引已自动过滤，无需每次执行。

**验收**：脚本在含 `credentials.json` 的旧库上执行后，`search_code`/RAG 不再命中；重复执行结果一致；有测试（mock DB）。

**工作量/风险**：0.5–1 天；删除 Qdrant 点需确认 point id 映射。

---

### A3. HTTPS / 公网入口确认（运维）

**现状**

- `docker-compose.yml` 的 app 暴露 `${BACKEND_PORT:-8000}:8000`；
- Caddy 是 `profiles: ["https"]` 可选服务；
- `remote-deploy.py` 生成的 `.env` 没设置 `COOKIE_SECURE`。

**方案**

- 确认线上 80 端口 docker-proxy 是否就是反代；如果没有，按 `docs/DEPLOY.md` 启用 Caddy；
- app 端口改为 `127.0.0.1:${BACKEND_PORT}:8000`，只让反代对外；
- `COOKIE_SECURE=true`，HTTP 301 到 HTTPS，加 HSTS；
- 证书自动续期验证。

**验收**：`curl http://域名` 301；`Set-Cookie` 带 `Secure`；8000 不对公网开放。

**工作量/风险**：0.5 天；需要你提供线上入口信息。

---

### A4. 服务器 E2E 与容器 smoke

**现象**

本轮本地无 Docker CLI，净化副本、只读 git、取消清理都只有单测，没有真实容器验证。上一轮 E2E 已经抓到“沙箱镜像没装 git”这种单测抓不到的问题。

**方案**

- 新增 `deploy/verify_security_e2e.py`（或扩展现有 `verify_*.py`）：
  1. readonly + `git status/diff/log` 通过；
  2. readonly/ask + `cat .env` 被拒绝；
  3. readonly + `grep -r SECRET .` 无命中；
  4. auto + `grep -r SECRET .` 无命中（A1 完成后）；
  5. 停止生成后 5 秒内无 `nova-sbx-*`；
  6. ZIP 导入后 Git 面板有 baseline commit；
  7. auto 编辑后 `search_code` 命中新内容。
- CI 增加 `docker build -f backend/Dockerfile.sandbox` + 容器 smoke（`git --version`、`pytest`、无网络、只读根）。

**验收**：脚本 7/7 通过；CI 容器 smoke 通过；结果贴进部署记录。

**工作量/风险**：1–2 天；依赖服务器可执行 Docker。

---

### A5. 本机执行器心跳的多 worker 问题

**现象**

`backend/app/core/local_bridge.py` 是进程内字典，单 worker 部署没问题；一旦 uvicorn 多 worker，心跳只落在其中一个进程，其他 worker 会把 `local_*` 工具隐藏。

**方案**

- 方案 A（推荐）：心跳落库 `local_agent_heartbeats(user_id PK, last_seen_at)`，轮询时 upsert，读取时 30 秒窗口；
- 方案 B：明确只支持单 worker，在 `run.py` 与部署文档中写死并校验；
- 方案 C：Redis，当前项目没有 Redis 依赖，不引入。

**验收**：2 worker 启动后，本机轮询 3 秒内 `local_*` 工具可见；心跳过期后自动隐藏；有测试。

**工作量/风险**：0.5–1 天；方案 A 增加一张小表，迁移简单。

---

## 3. Phase B：Agent 体验与交互（约 2–3 周）

### B1. Chat 级计划/待办（`update_plan`）

**现象**

Tasks/Changes/Builder 各自有步骤，但 chat 里没有计划；长任务容易漂移。`ToolCard` 也没有计划展示。

**方案**

- 新增 `update_plan` 工具：`{steps: [{title, status: pending|in_progress|completed}]}`，最多 12 步；
- 工具不触碰文件，所有模式可用；返回结构化 plan；
- loop 识别该工具，SSE 增加 `plan` 事件；消息 `tool_json.plan` 持久化；
- 前端新增 `PlanCard`，流式与历史消息都能渲染，支持当前步骤高亮；
- 系统提示词加一段“多步任务先建计划，执行中更新状态”。

**验收**：多步任务出现计划卡；步骤状态随执行更新；刷新历史仍在；单测覆盖工具 schema 与 SSE。

**工作量/风险**：2–3 天；注意别让模型每轮都重建计划（prompt + 去重）。

---

### B2. 工具输出流式与单工具取消

**现象**

`run_command` 最长 300 秒，前端只显示“正在执行”；`stdout` 要等命令结束才返回；没有单工具取消。`runtime._run_docker` 目前是 `subprocess.run`（Windows SelectorEventLoop 限制，见 `backend/app/core/sandbox/runtime.py` 注释）。

**方案**

- 运行时增加流式执行通道：
  - 用 `subprocess.Popen` + 两个 reader 线程 + `asyncio.Queue`（Windows/Linux 都能用），或 Linux 下 `asyncio.create_subprocess_exec`；
  - `execute(..., on_output=callback)` 按行/块回调，节流 100–200ms；
- `run_command` / `run_code` 支持 `stream=true`；loop 发出 `tool_output` SSE（`tool_call_id`, `stream`, `text`）；
- 新增取消通道：`POST /api/v1/chat/turns/{turn_id}/tools/{tool_call_id}/cancel`，进程内注册运行中的 `asyncio.Task`/容器名；取消时 kill 容器；
- 前端 ToolCard 增加终端视图、滚动输出、取消按钮；持久化 `stdout_tail/stderr_tail` 在历史里也渲染。

**验收**：长命令 1 秒内看到首行输出；取消后 2 秒内停止且无容器残留；历史消息能看到尾部输出；SSE 顺序稳定。

**工作量/风险**：4–6 天；跨平台子进程、SSE 背压、取消竞态是主要风险。

---

### B3. 内联命令审批（ask 模式）

**现象**

当前 `ask` 只允许只读 shell，任何会改动仓库的命令直接拒绝；没有“展示命令 → 用户批准 → 执行”的队列。`EditCard` 已经有编辑审批（diff + 批准/拒绝），但 shell 没有。

**方案**

- 策略层把 `run_command` 的 mutating/unknown 从“直接拒绝”改为“需要审批”（仅在 `ask` 模式；`readonly` 仍拒绝）；
- loop 在执行前发出 `tool_approval` SSE，暂停当前工具调用；
- 新增 `tool_approvals` 表（id, turn_id, tool_call_id, user_id, name, args, status, expires_at）；
- 前端 `ApprovalCard` 展示命令、风险等级、沙箱镜像、预计影响；批准/拒绝；
- `POST /tool-approvals/{id}/approve|reject` 唤醒等待中的 `asyncio.Event`；超时 5 分钟自动拒绝；
- 批准后按原参数执行，结果继续回填；审计记录批准人/时间；
- 多 worker 下需把等待队列放 DB/轮询或限定单 worker（与 A5 一起解决）。

**验收**：ask 下 `pytest`/`npm run build` 弹出审批；批准后真实执行；拒绝后模型收到“用户拒绝”；超时拒绝；审计可查。

**工作量/风险**：5–7 天；暂停/恢复生成器、超时、并发审批是主要风险。收益高：这是与 Claude Code/Codex 权限体验最直接的差距。

---

### B4. 前端工具卡升级与 `@` 文件提及

**现象**

- `ToolCard.tsx` 仍是通用 JSON：没有终端 ANSI、语法高亮、文件跳转、复制/重试/取消；
- `run_code`/`run_command` 的 `stdout_tail/stderr_tail` 已持久化（`loop.py`），但前端从未渲染；
- `Composer` 没有 `@` 提及实现，ChatView 占位符却写着“输入 @”；
- 编辑审批已有 `EditCard`（diff + 批准/拒绝），不要重复做。

**方案**

1. **按工具定制卡片**：
   - `run_command` / `run_code`：终端面板（ANSI 转义、自动滚动、退出码、耗时、复制、取消）；
   - `read_file`：语法高亮 + 行号 + “在工作区打开”；
   - `grep` / `glob` / `search_code`：结果列表，点击跳转到 `workspace?path=...&line=...`；
   - `edit_file` / `write_files`：复用 `DiffView`，显示增删行数；
   - 失败态：错误分类、重试按钮（重试即让模型重发同一工具调用）。
2. **`@` 文件提及**：输入 `@` 弹出仓库文件树搜索（复用 `/repos/{id}/tree`），选中后插入相对路径；后端无需新接口。
3. **历史回放**：`eventToCard` 传入 `stdout_tail/stderr_tail`，历史消息也能展开终端尾部。

**验收**：五类工具都有专用视图；文件链接能定位到工作区行号；历史消息可展开尾巴；`@` 能插入路径并高亮。

**工作量/风险**：3–5 天；依赖 B2 的流式数据结构；注意 bundle 体积（与 D6 一起做）。

---

### B5. 只读探索子代理（可选，P2）

**现象**：多文件探索仍是主上下文串行工具调用，慢且占 token。

**方案**：不做自由对话式多智能体，只做一个**只读子代理**：输入一个问题 + 仓库范围，独立上下文执行 `grep/glob/read_file/search_code`，输出结构化摘要 + 引用（文件:行号），主循环只接收摘要；token 预算上限、最大工具轮次、不可写。

**验收**：多文件探索轮次减少；引用可验证；预算超限时返回部分结果。

**工作量/风险**：3–4 天；收益依赖真实使用频率，放在 B1–B4 之后。

---

## 4. Phase C：检索与任务引擎（约 2–3 周）

### C1. 增量索引

**现象**

`backend/app/core/indexing/pipeline.py:306` 的 `reindex_repo` 直接 `DELETE` 全部 `repo_files/symbols/chunks` 并清空 Qdrant，改一个文件也要全量重建。

**方案**

- `repo_files` 增加 `content_hash`（或复用 size+mtime，但 hash 更稳）；
- 索引开始时先 walk 当前文件，计算 hash，与库中对比：
  - 新增/变更：只重建该文件的 symbols/chunks/embeddings；
  - 删除：删除该文件的派生数据与 Qdrant 点；
  - 未变：跳过；
- Qdrant point id 用 `file_id:chunk_index` 稳定映射；
- schema 版本变化或 `force=true` 时回退全量；
- 索引统计输出 `added/updated/deleted/skipped`，写进 job 结果与 UI。

**验收**：改 1 个文件只重嵌入 1 个文件；索引时间随变更量而不是仓库大小；删除文件后检索不再命中；全量回退可用。

**工作量/风险**：4–6 天；DB/Qdrant 一致性、部分失败重试是主要风险。

---

### C2. tree-sitter 符号索引

**现象**

非 Python 符号用正则（`backend/app/core/indexing/symbols.py`），TS/Go/Java 的嵌套、泛型、箭头函数边界容易错。

**方案**

- 引入 tree-sitter + 各语言 grammar（Python/TS/TSX/Go/Java/Rust）；
- 保留正则 fallback，解析失败自动降级；
- 为每种语言准备 fixture，断言符号名/行号/父子关系；
- 索引统计记录 parser 失败率。

**验收**：fixture 全通过；TS class/method、Go struct/func、Java method 边界准确；解析失败不阻断索引。

**工作量/风险**：3–4 天；依赖包体积与跨平台 wheel；作为可选依赖，缺包时降级。

---

### C3. 任务引擎统一（渐进式）

**现象**

四套引擎各自维护 step/gate/retry/approval：

- `backend/app/core/tasks/engine.py`（502 行，红绿 + 修复循环）
- `backend/app/core/changes/executor.py`（454 行，任务循环 + Gate + 修复）
- `backend/app/core/builder/engine.py`（859 行，方案 → 文件 → 双栈 Gate）
- `backend/app/core/night/service.py`（343 行，队列与预算）

每加一种任务都要改多套；gate 压缩、失败文本、repair 尝试逻辑重复。

**方案**

- 抽 `core/runs/` 共享原语：`Run`（状态机）、`Step`（状态/耗时/输出）、`GateResult`（统一结构）、`repair_loop`（最大次数、反馈拼接）、`approval`；
- 先做适配层，不搬业务：tasks/changes/builder 各自实现 `RunAdapter`，复用共享 gate 压缩与修复循环；
- 每迁移一套保持测试全绿，最后删重复代码；
- night 不并入，继续做调度器。

**验收**：三套引擎行为不变；重复 gate/repair 代码减少；新增一种任务只需实现 adapter；测试覆盖。

**工作量/风险**：6–8 天；重构风险高，建议在 C1/C2 之后、有稳定测试网时做。

---

## 5. Phase D：平台与运维（持续）

### D1. CI/CD 与镜像预构建

**现状**

`.github/workflows/ci.yml` 只跑 lint、单元测试、前端构建、契约检查；没有镜像构建、容器 smoke、fake-LLM E2E。服务器 2C2G 上现场 `docker compose build` 需要数分钟。

**方案**

- CI 增加 job：
  1. 构建 `app` / `nova-sandbox` / `nova-builder` / `nova-node` 镜像并推 GHCR（tag: sha + latest）；
  2. 容器 smoke：`git --version`、pytest、网络禁止、只读根、非 root；
  3. fake-LLM E2E：启动 Postgres + Qdrant service，脚本化 LLM 走 read → edit → gate → report，校验 SSE/DB；
- 服务器部署改为 `docker compose pull && up -d`，保留人工确认，不自动上线；
- 补 `workflow_dispatch` 手动发布。

**验收**：部署时间 < 5 分钟；CI < 15 分钟；镜像可回滚到 sha tag；E2E 在 CI 稳定通过。

**工作量/风险**：2–3 天；GHCR 权限、ARM/AMD 架构、CI 服务容器是主要工作。

---

### D2. 备份与恢复演练

**现状**

`docs/DEPLOY.md` 只有手工 `pg_dump` / volume tar 命令，没有定时任务和恢复演练。

**方案**

- `deploy/backup.sh`：`pg_dump`、Qdrant snapshot API、repos volume tar；保留 7 日 + 4 周；
- systemd timer 或宿主机 cron；
- `deploy/restore.sh` + 文档：恢复到全新 compose，校验用户/仓库/索引可查；
- 备份文件加密与异地（可选）。

**验收**：恢复演练一次成功；RPO/RTO 写清楚；备份失败有告警日志。

**工作量/风险**：1–2 天；Qdrant snapshot 与 volume 一致性需注意。

---

### D3. 工具级可观测

**现状**

`backend/app/core/metrics/service.py` 只有变更/任务/用量/job p95，没有工具级指标；trace 有逐次工具事件但没有聚合。

**方案**

- 从 `trace_events` 或 `tool_events` 聚合：按工具统计调用数、成功率、p50/p95 耗时、错误分类（policy/business/infra）、token 成本；
- 每日 rollup 表或物化视图，避免实时扫大表；
- API + 前端“工具健康”面板；
- 阈值告警：某工具成功率 < 90% 或 p95 > 30s。

**验收**：能看到 top 失败工具与 p95；策略拒绝率趋势；成本按工具拆分。

**工作量/风险**：2–3 天；数据量增长后需要 rollup。

---

### D4. 原生 Provider 与 prompt caching

**现状**

只有 `OpenAICompatibleLLM`（DashScope/LongCat），没有 Anthropic 原生 tool use、Gemini 原生、prompt caching。

**方案**

- 新增 `AnthropicLLM`（原生 tools + `cache_control`）与 `GeminiLLM`（function calling）；
- `supports_tools` 已就绪，回退链自动过滤；
- `parallel_tool_calls` / `tool_choice` 可配置；
- 缓存命中 token 计入 usage，前端展示缓存节省；
- 评测：同一长工具循环的延迟/成本对比。

**验收**：Anthropic 缓存命中可见；coding 回退不退化；成本对比有数据。

**工作量/风险**：4–6 天；多 SDK、流式差异、错误映射是主要工作。

---

### D5. MCP 生态扩展

**现状**

`backend/app/core/mcp/client.py` 是 stdio 最小实现；没有 HTTP/SSE、OAuth、tool annotations、progress。

**方案**

- 支持 streamable HTTP / SSE transport；
- OAuth / API key 配置；
- tool annotations（readOnly/destructive/idempotent）映射到能力策略；
- progress notification 转 SSE；
- MCP 进程仍走沙箱/allowlist，不直接放开。

**验收**：接入一个 HTTP MCP server；destructive 注解工具在 readonly 被拒；progress 可见。

**工作量/风险**：4–6 天；协议版本与鉴权是主要风险。

---

### D6. 前端代码分割与体积预算

**现状**

生产构建单 chunk `767.52 kB`（gzip 230 kB），`App.tsx` 静态导入全部视图；Vite 配置没有 manualChunks。

**方案**

- `React.lazy` + `Suspense` 拆分 Tasks/Settings/Workspace；
- `manualChunks` 拆 vendor / markdown / syntax-highlight；
- 设定 bundle 预算（首屏 < 500 kB gzip 后 < 180 kB），CI 检查；
- 语法高亮按需加载。

**验收**：首屏 chunk 明显下降；路由切换正常；CI 体积检查。

**工作量/风险**：1–2 天；低风险。

---

### D7. 桌面端与本机执行器

**现状**

- `desktop/` 是 Electron 外壳，CI 已能在三平台打出安装包（`.github/workflows/desktop.yml`），但没有自动更新、代码签名、开机启动、系统托盘；
- 本机执行器是 `backend/nova.py agent` CLI，命令确认在终端里完成，桌面端没有原生确认弹窗；
- 断线重连、离线队列、路径 allowlist 都依赖用户手动处理。

**方案**

- 接入 `electron-updater` + GitHub Release 自动更新；
- Windows/macOS 代码签名（至少 Windows），去掉 SmartScreen 警告；
- 托盘常驻 + 开机启动 + 断线指数退避重连；
- 桌面端内置/托管本地执行器，命令确认改为原生对话框（显示命令、cwd、风险等级），不再依赖终端；
- 本机路径 allowlist + 审计，拒绝越界路径；
- 与 B3 的服务端审批共用一套风险分级文案。

**验收**：安装 → 配置服务器 → 断线自动恢复；本机命令弹原生确认；新版本可自动更新；签名安装包无警告。

**工作量/风险**：3–5 天；签名证书、macOS 公证、自动更新渠道是主要工作。

---

### D8. 测试体系提速

**现状**

本地全量 `502 passed` 耗时 8 分 31 秒，大量时间花在 trace/audit 的 DB 连接超时；CI 没有服务时集成测试跳过，但单测仍会尝试 DB。

**方案**

- 增加 `NOVA_TEST_FAST=1`：trace/audit/usage 全部 no-op 或内存队列；目标全量 < 2 分钟；
- fake-LLM 确定性 E2E（SSE 顺序、审批、索引、取消）；
- 集成测试统一标记 `integration`，CI 用 service containers 单独 job；
- 测试数据工厂，减少重复 mock。

**验收**：快跑 < 2 分钟；CI 单元与集成分开；E2E 稳定。

**工作量/风险**：2–3 天；需要逐个模块替换 DB 调用，注意不要掩盖真实错误。

---

## 6. 建议路线图

| 周 | 重点 | 交付 |
|---|---|---|
| 第 1 周 | A1/A2/A4/A5 + A3 运维确认 | auto 密钥收口、旧索引清理脚本、服务器安全 E2E 7/7、心跳落库 |
| 第 2 周 | B1 + B4 前半 | `update_plan` + 计划卡；终端/文件跳转/历史尾巴；`@` 提及 |
| 第 3 周 | B2 | 流式工具输出 + 单工具取消 + 前端终端 |
| 第 4 周 | B3 | ask 模式命令审批（暂停/批准/拒绝/超时） |
| 第 5 周 | C1 | 文件级增量索引 + 统计 |
| 第 6 周 | C2 + D1/D2 | tree-sitter；CI 镜像/容器 smoke；备份脚本 |
| 第 7–8 周 | C3 + D3 | 任务引擎适配层；工具级指标面板 |
| 持续 | D4/D5/D6/D7/D8 | 原生 provider、MCP 扩展、代码分割、桌面端、测试提速 |

**依赖关系**

- B2 依赖 A4（容器可观测）与 B4 的数据结构；
- B3 依赖 A5（多 worker 等待队列）；
- C3 依赖 D7（稳定测试网）；
- D1 依赖 A4（容器 smoke 脚本）。

---

## 7. 验收指标

### 安全

- readonly/ask/auto/full 四种模式下，显式与间接密钥读取均被拒绝；
- 旧索引清理脚本执行后，`search_code`/RAG 无密钥路径；
- 停止生成 5 秒内无 `nova-sbx-*` 残留；
- 公网强制 HTTPS，cookie 带 `Secure`。

### 正确性

- auto 编辑后 `search_code` 命中新内容；
- ZIP 导入后 Git 面板可用，批准修改有 commit；
- 长任务 > 12 轮不超窗，压缩有指标；
- 增量索引改 1 文件只重嵌入 1 文件。

### 体验

- 长命令 1 秒内看到首行输出，可取消；
- ask 下写命令有审批卡，批准后执行；
- 工具卡有终端/diff/文件跳转；历史可回放；
- `@` 文件提及可用。

### 工程

- 快跑测试 < 2 分钟；全量测试 + E2E 在 CI 稳定；
- 部署 < 5 分钟，镜像可回滚；
- 备份恢复演练成功；
- 首屏 bundle 预算达标。

---

## 8. 面试/演示优先级（结合你的求职目标）

**高信号、优先展示**

1. **A1+A2 安全边界**：能讲清楚“分类器不是安全边界，净化工作区/遮蔽才是”，并给出攻击链与修复证据。
2. **B3 命令审批**：暂停生成 → 用户批准 → 恢复执行，是权限状态机的完整案例。
3. **B2 流式与取消**：跨平台子进程、SSE、容器清理，工程复杂度高、可演示。
4. **D3 工具级指标**：用真实数据回答“哪个工具最容易失败、p95 多少”，比泛泛而谈“可观测”更有说服力。

**高投入、低演示价值，建议后置**

- C3 任务引擎统一：重构收益真实，但面试展示不如 B2/B3 直观，且风险高。
- D5 MCP OAuth/HTTP：除非目标岗位明确要求 MCP 生态。
- B5 子代理：容易变成“多智能体表演”，除非有真实 token/延迟收益数据。

**建议演示脚本（5 分钟）**

1. readonly 下让模型读 `.env` → 被拒绝；
2. 切 auto，`grep -r SECRET .` → 无命中（A1 后）；
3. 让模型改一个文件 → 索引自动重建 → `search_code` 命中新内容；
4. 跑长命令 → 实时输出 → 取消 → 无容器残留；
5. ask 下跑 `pytest` → 审批卡 → 批准 → 真实通过；
6. 打开本轮交付报告：证据、退出码、token、耗时。

---

## 9. 已知小项与技术债

这些不单独排期，但建议在对应阶段顺手处理：

- `ToolRegistry.specs(sandbox_available=...)` 参数已支持，但 chat loop 目前没有传入；Docker 不可用时仍会下发 `run_code/run_command`（调用时如实报错）。接入一个缓存的沙箱状态即可。
- 上下文计量 UI 仍显示默认窗口；压缩已按 BYOK 真实窗口执行，展示值可后续对齐。
- ZIP 导入的 Git baseline 在 upload 请求内同步执行，超大 ZIP 会增加上传耗时；可移到索引 job 里。
- 净化副本会跳过 `node_modules/.venv` 等重目录，只读模式下 `ls node_modules` 不可用；这是性能取舍，建议在工具说明里写清楚。
- `fetch_url` 默认仍为 true；公网部署建议显式关闭或配置 `FETCH_URL_ALLOWED_DOMAINS`。
- `local_bridge` 是进程内心跳，单 worker 限制由 A5 解决。
- 本地全量测试约 8.5 分钟，主要耗在 trace/audit 的 DB 超时；由 D8 的快速测试档解决。
- 前端单 chunk 767KB；由 D6 解决。
- `stdout_tail/stderr_tail` 已持久化但前端未渲染；B4 顺手做掉。

---

## 10. 不建议做的事（YAGNI）

- 不重写现有证据化交付、Gate、Reviewer、沙箱、多用户隔离；
- 不做自由对话式多智能体；
- 不引入图数据库/Redis（除非多 worker 心跳必须）；
- 不急于做 IDE 插件/实时补全；
- 不做全自动部署，保持人工批准；
- 不为了“对齐 Claude Code”而复制所有功能，优先保留 Nova 的差异化：可验证交付 + 自托管 + 确定性 Gate。

---

## 11. 关键文件索引

| 主题 | 文件 |
|---|---|
| 安全策略/密钥 | `backend/app/core/security/policy.py`、`paths.py`、`commands.py` |
| 沙箱运行时 | `backend/app/core/sandbox/runtime.py` |
| 工具注册/裁剪 | `backend/app/core/tools/base.py`、`__init__.py` |
| Agent 循环/上下文 | `backend/app/core/agent/loop.py`、`context_governor.py`、`context_meter.py` |
| 工具输出 | `backend/app/core/agent/tool_output.py` |
| 索引/检索 | `backend/app/core/indexing/pipeline.py`、`symbols.py`、`core/rag/` |
| 编辑/审批 | `backend/app/core/editing/service.py`、`frontend/src/components/EditCard.tsx` |
| 任务/变更/Builder | `backend/app/core/tasks/`、`changes/`、`builder/`、`night/` |
| 前端工具卡 | `frontend/src/components/ToolCard.tsx`、`MessageBubble.tsx`、`Composer.tsx` |
| 指标 | `backend/app/core/metrics/service.py`、`backend/app/core/trace.py` |
| CI/部署 | `.github/workflows/ci.yml`、`desktop.yml`、`deploy/`、`docker-compose.yml` |
| 桌面/本机 | `desktop/main.js`、`backend/nova.py`、`backend/app/api/v1/local_exec.py` |

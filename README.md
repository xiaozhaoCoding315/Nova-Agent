# Nova Agent — 可验证的工程 Agent

一个**可自托管**的开发者 AI 工作台。不止于聊天：它会给结论附证据、算清改动影响面、在沙箱里复现 bug 并交付经过红-绿验证的补丁。

## 差异化能力

| 能力 | 说明 |
|---|---|
| **证据化回答** | 每条回答自动校验引用：`文件:行号` 是否真实存在、行号是否越界；涉及运行的结论标记「沙箱实测」。前端以证据条展示，幻觉引用会被标出。 |
| **变更影响雷达** | 基于导入依赖图 + 符号引用，回答「改这个函数会影响什么」：直接/间接依赖文件、引用位置、相关测试、风险等级，并给出建议测试命令。 |
| **项目大脑** | 索引后自动生成模块地图、入口点、热点文件、推荐阅读顺序、依赖图与术语表（全部确定性生成），随重建索引更新。 |
| **复现-修复闭环（红-绿任务）** | 贴一段 bug 描述：自动生成失败测试（红，校验测试确实运行且失败）→ 产出最小补丁 → 全量测试复跑（绿，最多自动修复 3 次）→ 展示 diff 与真实测试输出 → **你批准后**才写入仓库并重建索引；文件在生成后被改动会拒绝覆盖。 |
| **Git 交付与轨迹回放** | 工作区可一键初始化 Git、提交、查看 diff、回滚（自动重建索引）、导出 zip；每次对话/工具/审批全程记录轨迹，可在「轨迹」抽屉回放。 |
| **栈感知验证** | 工作区/Builder 里点「验证」：自动识别 Python 项目，依次执行语法检查、pytest、可选的 ruff/mypy，逐项返回命令、退出码与输出；依赖可持久化安装到仓库级依赖卷。 |
| **只读 Reviewer** | 对编辑提案和红绿任务 diff 做独立审查：输出 `pass / warn / block`、blocking / non-blocking 与依据；审查员没有任何写入或执行工具。 |
| **交付报告** | 每轮对话自动生成结构化报告：执行命令与退出码、改动文件、引用核对、未验证项、token 用量和耗时，历史消息可回看。 |
| **对话内改代码（权限 + 快照）** | 在对话里直接读文件、改文件：只读 / 确认 / 自动三档权限；确认模式先生成 diff 提案，批准后才写入；每次写入保存快照，可一键撤销。 |
| **从 0→1 建项目（Builder）** | 描述需求 → 生成结构化方案（技术栈/目录/数据模型/API/里程碑/风险）→ 确认后生成完整项目文件提案 → 逐文件审阅 → 批准写入并自动索引。MVP 支持 Python 后端（FastAPI + SQLite + pytest）。 |
| **变更工作流（SPEC → 计划 → Gate → 审查 → 应用）** | 用自然语言提功能/重构需求：起草 SPEC（目标/In-Out/接口/验收）→ 人工冻结 → 拆成带依赖和可判定验收的任务 → 串行执行，每个任务过真实 Gate（失败摘要回喂，最多 3 次）→ 汇总统一 diff 提案 → 只读审查 → 人工批准后写入并重建索引。 |

## 解决什么问题

写代码时最常卡住的四件事，Nova 都有对应的确定性能力（不是"让模型自由发挥"）：

| 场景 | 怎么用 | 背后机制 |
|---|---|---|
| **读懂陌生代码库** | 导入仓库（ZIP / Git URL），直接问「X 功能在哪个文件实现的？」 | 符号级代码索引（函数/类/接口）+ 语义与关键词双路检索，回答携带 `文件:行号` 引用 |
| **排查报错** | 贴 Python / JVM / Node / Go 堆栈 | 确定性解析错误类型、消息与调用帧 → 在仓库中定位对应文件 → 结合检索给出修复建议 |
| **验证代码/生成测试** | 「给这个函数写单测，并跑通」 | LLM 写代码 → **Docker 沙箱真实执行** → 读取 stdout/退出码 → 自我纠错迭代（≤5 轮），直到测试全绿 |
| **复现 bug 并交付补丁** | 贴 bug 描述，进入「任务」 | 失败测试（红）→ 最小补丁 → 复跑（绿）→ 人工批准后写入仓库 |
| **评估改动风险** | 「改这个函数会影响什么？」 | 依赖图 + 符号引用算出受影响文件/测试与风险等级，并建议测试命令 |
| **从 0 建一个新项目** | 工作区 →「新建项目」 | 方案 → 确认 → 文件提案 → 审阅 → 写入/索引，全程有审批栅栏 |
| **日常杂活** | JSON/YAML 校验转换、SQL 审阅、抓取在线文档 | json_tool / sql_tool / fetch_url，全部确定性实现，结果即真相 |

## 核心特性

### 代码感知的混合检索
- **符号索引**：Python 用 AST、Java/TS/JS/Go 等用结构化正则，按函数/类边界提取符号表（名称、类型、起止行号）
- **双路召回 + RRF 融合**：Qdrant 稠密向量（语义）+ PostgreSQL 全文（jieba 中文分词预处理）并行检索，单路故障自动降级
- **引用可核对**：每条命中都带真实 `路径:行号`，前端可一键复制引用

### Agent 循环 + Function-Calling
- 11 个工具：`read_file` / `list_files`（精确读码）、`write_files`（带 diff、审批与快照的写入）、`run_code`（沙箱执行，可切换 builder 环境）、`install_deps`（管理员联网安装依赖到仓库依赖卷）、`diagnose_error`（堆栈解析+仓库定位）、`search_code`（符号+混合检索）、`impact_analysis`（变更影响面）、`json_tool`、`sql_tool`、`fetch_url`（带 SSRF 防护）
- 工具调用全链路可视：SSE 实时推送 `tool_call` / `tool_result` 事件，前端渲染工具卡片（入参 / 结果 / 耗时）
- 项目规则：关联仓库根目录的 `AGENTS.md`（兼容 `CLAUDE.md`）会注入系统提示词，仓库约定不再靠口头提醒
- 工具执行纳入容错框架：分级超时（LLM 90s / 检索 10s / 工具 30s）、指数退避重试、熔断降级；业务性失败（参数错误、配额）与基础设施故障区分统计
- 每轮结束生成确定性交付报告（命令/退出码/改动/引用/未验证项），随消息持久化，不靠模型自述"完成了"

### Docker 安全沙箱（绝不降级）
- LLM 生成的代码只在锁定容器中执行：**禁网络 + 只读根文件系统 + 丢弃全部 capabilities + 非 root uid + pid/内存/CPU 限额**
- 沙箱镜像预装 numpy / pytest，「写测试 → 运行 → 迭代」开箱即用
- Docker 不可用时工具**如实标记不可用**，绝不退化为在宿主机执行

### 产品化能力
- **登录认证**：JWT（httpOnly cookie）+ bcrypt；`admin` / `demo` 双角色，demo 账号供演示访问且带限额（10 条/小时、每日 token 预算、沙箱次数）
- **会话持久化**：历史会话、消息与关联仓库落库，刷新不丢；支持停止生成（断流后已生成内容仍会保存）
- **真实健康检查**：PG / Qdrant / LLM / Embedding / 沙箱逐项探活，降级可见
- **审计与配额**：登录、对话、工具调用、仓库导入/删除全量审计；对话/红绿任务/Builder/记忆抽取统一 LLM 记账，导入/重建索引/验证/搜索均有独立配额
- **持久后台队列**：索引 / 红-绿 / Builder / 会话摘要写入 PostgreSQL `jobs` 表，支持重启恢复、取消与重试；后台入口不再直接 `create_task`

### 两层记忆
- 会话记忆：持久化消息 + 滚动摘要（每 20 条增量压缩并注入后续轮次）+ 标题自动生成
- 长期记忆：对话中抽取用户偏好/事实，按用户隔离去重（MD5 + 向量相似度 0.92），重要性访问加权、闲置衰减、TTL 过期清理（小时级维护循环）

## 技术栈

| 层 | 选型 |
|---|---|
| 后端 | Python 3.12 · FastAPI · 自研 Agent 循环（无 LangChain 黑盒） |
| 前端 | React 18 · TypeScript · Vite · TailwindCSS · Zustand · react-markdown + highlight.js |
| 存储 | PostgreSQL 16（业务/会话/记忆/全文检索）· Qdrant（稠密向量） |
| LLM | 阿里云百炼 `qwen3.8-max`（OpenAI 兼容，默认单通道；可配置 deepseek/longcat 降级链） |
| 沙箱 | Docker（一次性容器，强隔离） |
| 部署 | Docker Compose（app + postgres + qdrant + 沙箱镜像）· 可选 Caddy 自动 HTTPS |

## 快速开始

### 方式一：Docker Compose 一键部署（推荐）

```bash
cp .env.docker.example .env   # 填入 LLM API Key，修改 SECRET_KEY 与两个账号密码
docker compose up -d --build  # 构建并启动全部服务
# 访问 http://<服务器IP>:8000
```

首次启动自动完成幂等初始化：建库建表、创建 Qdrant collection、生成 admin/demo 账号。

启用 HTTPS（有域名时）：`cp Caddyfile.example Caddyfile` 改成你的域名，然后 `docker compose --profile https up -d`，并在 `.env` 中设 `COOKIE_SECURE=true`。

### 方式二：本地开发

```bash
# 后端（本机进程，热重载）
cd backend
pip install -r requirements.txt
cp .env.example .env          # 配置 PG/Qdrant 地址与 LLM Key
python run.py                 # http://localhost:8000

# 前端（Vite 开发服务器，代理到 8000）
cd frontend
npm install
npm run dev                   # http://localhost:5173
```

说明：
- 沙箱工具需要本机 Docker 在运行；未运行时设置页会如实显示「沙箱不可用」，其余功能不受影响
- 首次启动设 `AUTO_INIT_DB=true` 自动建表，或手动执行 `python -m app.db.init_db`

## 配置项（.env 关键项）

| 变量 | 说明 |
|---|---|
| `DEEPSEEK_API_KEY` / `DASHSCOPE_API_KEY` | LLM Key（至少一个；DashScope 同时提供 embedding） |
| `DASHSCOPE_MODEL` | 阿里云百炼模型名（默认 `qwen3.8-max`） |
| `LLM_MODEL_PRIORITY` | 模型通道顺序，默认 `dashscope`；可写 `dashscope,deepseek,longcat` 启用降级链 |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | 管理员账号（启动时注入/更新） |
| `DEMO_USERNAME` / `DEMO_PASSWORD` | 演示账号（可公开给面试官/朋友使用） |
| `SECRET_KEY` | JWT 签名密钥（≥32 位随机串） |
| `COOKIE_SECURE` | 启用 HTTPS 后设为 true |
| `DEMO_DAILY_TOKENS` / `DEMO_HOURLY_MESSAGES` / `DEMO_SANDBOX_DAILY` | 演示账号限额（0 = 不限） |
| `ADMIN_JOB_HOURLY` / `DEMO_JOB_HOURLY` | 导入 / 重建索引 / 验证 / 红绿任务 / Builder / 只读审查每小时次数（0 = 不限） |
| `SANDBOX_ENABLED` | 沙箱总开关 |
| `MAX_UPLOAD_MB` / `MAX_REPO_FILES` | 仓库导入上限 |

## API 概览

| 端点 | 说明 |
|---|---|
| `POST /api/v1/auth/login` `logout` `GET me` | 登录 / 登出 / 当前用户 |
| `GET/POST /api/v1/chat/sessions` | 会话列表 / 新建 |
| `GET /api/v1/chat/sessions/{id}/messages` | 历史消息 |
| `POST /api/v1/chat/message` | 对话（SSE：`meta/retrieval/token/tool_call/tool_result/usage/error/done`） |
| `POST /api/v1/repos/upload` / `POST /api/v1/repos/git` | 导入仓库（ZIP / 公开 Git URL） |
| `GET /api/v1/repos` `/{id}` `/{id}/tree` `/{id}/file` `/{id}/search` | 仓库列表 / 详情 / 文件树 / 文件内容 / 仓库内搜索 |
| `GET /api/v1/repos/{id}/brain` | 项目大脑（地图/入口/阅读顺序/依赖图/术语表） |
| `GET /api/v1/repos/{id}/impact?q=` | 变更影响分析（依赖面/引用/测试/风险） |
| `POST /api/v1/tasks` · `GET /tasks` `/{id}` | 创建修复任务（红-绿）/ 列表 / 详情 |
| `POST /api/v1/tasks/{id}/apply` · `/reject` | 批准写入仓库（自动重建索引）/ 拒绝 |
| `POST /api/v1/repos/builder` | 新建项目：需求 → 生成结构化方案 |
| `GET /api/v1/repos/{id}/plan` · `POST .../plan/approve` · `POST .../plan/generate` | 查看 / 确认 / 重新生成方案 |
| `POST /api/v1/repos/{id}/generate` · `GET .../proposal` | 生成文件提案 / 查看提案 |
| `POST /api/v1/repos/{id}/proposal/approve` · `/reject` | 批准写入并索引 / 退回重做 |
| `GET /api/v1/edits/{id}` · `POST .../approve` `.../reject` `.../revert` `.../review` | 对话内修改：查看提案 / 批准 / 拒绝 / 快照撤销 / 只读审查 |
| `POST /api/v1/tasks/{id}/review` | 对红绿任务 diff 做只读审查（pass / warn / block + 依据） |
| `GET /api/v1/jobs` · `GET /jobs/{id}` · `POST /jobs/{id}/cancel` · `POST /jobs/{id}/retry` | 后台任务：列表 / 详情 / 取消 / 重试（索引、红绿、Builder、变更、会话摘要） |
| `POST /api/v1/changes` · `GET /changes` `/{id}` · `PATCH /changes/{id}` | 创建变更（自动起草 SPEC）/ 列表 / 详情 / 编辑 SPEC |
| `POST /changes/{id}/approve` · `/plan` · `/plan/approve` · `/execute` | 冻结 SPEC / 生成计划 / 批准计划 / 执行计划 |
| `POST /changes/{id}/apply` · `/reject` · `/cancel` · `GET /changes/{id}/report` | 应用提案（含 Gate/Review 证据）/ 拒绝 / 取消 / 交付报告 |
| `POST /api/v1/repos/{id}/verify` · `GET .../verify` | 栈感知真实验证（语法 / pytest / 可选 lint / 类型检查，逐项结果）/ 查看上次结果 |
| `GET /repos/{id}/git` · `POST /git/init` `/git/commit` `/git/rollback` · `GET /git/diff` | Git 状态 / 初始化 / 提交 / 回滚 / diff |
| `GET /repos/{id}/export` | 导出仓库 zip（不含 .git） |
| `GET /chat/sessions/{id}/trajectory` | 会话全链路轨迹（用户/检索/模型轮次/工具/审批） |
| `GET /api/v1/status/health` / `usage` | 依赖探活 / 用量配额 |

## 项目结构

```
backend/app/
├── api/v1/            auth · chat · repos · tasks · builder · changes · git · jobs · status
├── core/
│   ├── agent/loop.py  Agent 主循环（检索→工具轮次→证据校验→持久化）
│   ├── agent/evidence.py  引用校验（文件/行号/越界）
│   ├── rag/           双路召回 + RRF（dense / keyword）
│   ├── indexing/      仓库索引：walker / symbols / chunker / imports / brain / pipeline
│   ├── impact/        变更影响分析（依赖图 + 符号引用）
│   ├── jobs/          持久后台队列（claim / 心跳 / 恢复 / 取消 / 重试）
│   ├── changes/       SPEC / Planner / 串行执行器 / Gate / 任务模板
│   ├── tasks/         红-绿修复任务引擎（复现→补丁→全量验证→审批）
│   ├── verify/        栈感知验证 profile（语法/pytest/可选 lint/类型检查）
│   ├── review/        只读 Reviewer（pass/warn/block + 依据）
│   ├── builder/       从 0→1：方案生成 + 文件提案（人工审批后写入）
│   ├── editing/       对话内编辑：diff / 审批 / 快照撤销 / 冲突检测
│   ├── git_ops/       Git 交付：初始化/提交/diff/回滚/导出
│   ├── trace.py       轨迹事件记录（回放 / CI 审计）
│   ├── memory/        会话摘要 + 长期事实（去重/衰减/清理）
│   ├── tools/         11 个工具 + 注册表（校验/容错/审计）
│   ├── sandbox/       Docker 一次性容器执行器
│   ├── harness/       超时 / 重试 / 熔断
│   ├── security/      认证 / 限流配额 / 风险规则 / 审计
│   └── llm/           多厂商降级链 + 工具流式（真实 token 统计）
├── db/                PostgreSQL 连接 · Qdrant · 幂等初始化
└── models/            Pydantic 模型
frontend/src/
├── views/             登录 · 对话 · 工作区 · 变更中心 · 任务 · 设置
├── components/        消息/工具卡片/证据条/项目地图/影响分析/文件树/代码查看器…
├── stores/            auth · chat · repos（Zustand）
└── lib/               API 客户端 · SSE 解析（含中断与错误处理）
docs/DESIGN.md         架构设计文档（数据模型/API/安全/部署）
contracts/openapi.json FastAPI 导出的单一契约源（提交）
frontend/src/lib/api-schema.d.ts  由契约生成的 TS 类型（提交）
backend/scripts/export_openapi.py 契约导出/--check 脚本
frontend/scripts/contract-check.mjs 前端契约类型漂移检查
```

## Headless CLI（CI 友好）

```bash
cd backend
python nova.py repos --json
python nova.py run "这个仓库有哪些接口？" --repo todo-api --permission readonly --json
python nova.py verify --repo todo-api --json      # 退出码：0 通过 / 1 失败
python nova.py trajectory --session <uuid> --json
python nova.py export --repo todo-api --out todo-api.zip
```

环境变量：`NOVA_URL`（默认 `http://localhost:8000`）、`NOVA_USERNAME`、`NOVA_PASSWORD`。
`run --json` 输出逐行 SSE 事件（JSONL），默认权限为只读，适合放在 CI/自动化里跑验证与问答。

## 测试

```bash
cd backend && python -m pytest tests/ -q
cd frontend && npm run build
cd frontend && npm run contract:check   # OpenAPI 与生成类型是否同步
```

- 单元测试（无需数据库）：认证/限流、Agent 循环事件协议与停止语义、工具、索引与分块、导入图解析、证据校验、ZIP 安全、SSRF 防护、熔断重试、变更工作流、任务队列、记忆摘要
- 契约测试（无需数据库）：`tests/test_contract.py` 校验 `contracts/openapi.json` 与运行中的应用一致
- 集成测试（标记 `integration`，连不上 PG/Qdrant 时自动跳过）：建库建表幂等性、账号种子

### 契约生成与漂移检查

```bash
# 后端：从 FastAPI 导出唯一契约源
cd backend && python -m scripts.export_openapi

# 前端：由契约生成 TS 类型并校验是否过期
cd frontend && npm run contract:generate
cd frontend && npm run contract:check
```

`contracts/openapi.json` 是提交到仓库的契约快照；`frontend/src/lib/api-schema.d.ts` 由 `openapi-typescript` 生成。修改后端响应模型后必须重新导出/生成，否则 `contract:check` 退出码 1。

## 安全说明

- 代码执行只在锁定沙箱中进行；Docker 不可用时工具不可用，不存在宿主机执行路径
- 文件工具统一走路径解析器：拒绝绝对路径、`..` 穿越、同前缀兄弟目录与符号链接逃逸；`.env`、私钥、凭据文件禁止读取与写入
- 测试保护：修改已有测试文件时禁止删除测试或新增 skip 标记；红绿任务必须新建测试文件
- `fetch_url` 有 SSRF 防护：仅公网 http(s)、逐跳校验重定向、拒绝内网地址、限制响应大小与类型
- ZIP 导入有路径穿越防护、文件数与大小上限；Git 仅支持公开仓库浅克隆
- 部署暴露公网前请务必：改 `SECRET_KEY`、改两个账号密码、按需收紧 `CORS_ORIGINS`

## 已知边界

- 沙箱执行仅 **Python**；`nova-sandbox` 预装 numpy/pytest，`nova-builder` 额外预装 fastapi/uvicorn/httpx/pydantic，用于真实跑仓库测试；JS/Java 只做静态分析，不能执行
- 联网装依赖默认关闭（`SANDBOX_ALLOW_NETWORK=false`），开启后仅管理员可用；依赖持久化在 `nova-deps-<repo>` Docker 卷
- 影响分析是**静态分析**（导入图 + 符号引用），不是编译器级调用图
- 验证 profile 目前覆盖 **Python**（compileall + pytest + 可选 ruff/mypy）；Node/前端项目会如实标记 `unsupported`，不会假装通过
- 红-绿任务面向 **Python/pytest** 仓库效果最好；绿阶段跑全量测试，补丁需人工批准
- Reviewer 是一次结构化只读审查，不是多智能体辩论；它的结论作为证据补充，不替代人工审批
- Builder MVP 只生成 **Python 后端**项目；已接入 `nova-builder` 真实跑 pytest（含依赖卷），但**不启动常驻服务**（无端口预览）
- 账号体系为 admin/demo 两级，不开放自助注册
- Git 回滚使用 `git reset --hard`，会丢弃未提交改动（前端有二次确认）；未初始化 Git 的仓库不会自动提交
- 轨迹目前记录对话链路与审批事件，不支持按任意历史步骤“从中间重放执行”
- 变更工作流当前按任务**串行**执行，生成完整文件而非 patch；Gate 仍只支持 **Python**（compileall + pytest + 可选 ruff/mypy），Node/前端项目会标记 `unsupported` 并明确写入未验证项；尚未引入每任务独立分支/worktree
- 契约生成已接入（OpenAPI → TS），但前端仍保留手写 UI 类型别名；逐域迁移与契约 Gate 属于 P2 后续
- `contract:check` 需要本机 Python 与 Node 依赖；CI 接入属于 P2 后续

## License

个人项目，供学习与演示使用。
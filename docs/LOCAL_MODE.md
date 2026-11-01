# 本地模式（Windows 11）

本地模式让同一套 Nova 后端在你自己电脑上运行：内嵌 PostgreSQL（默认 `pgserver`，可回退系统 `pg_ctl`）、固定本地用户、直接打开本地文件夹、无容器 HostExecutor、无 Qdrant 的关键词/符号检索、单 worker 后台任务。

**边界：Nova 不向 Nova 服务器上传代码、不发送遥测、不访问 Nova 服务器。** 除你配置的 LLM API 外，只有你显式使用的联网工具或操作（`fetch_url`、`install_deps`、Git 导入，以及在 `auto` / `full` 下或 `ask` 中经批准后运行的 `run_command` / `run_code`）会访问外部网络，且受权限模式与审批约束。

## 1. 前置条件

- Windows 11（v1 验收平台）
- Python 3.12
- Git（可选）：Git 可用且目录是 Git 仓库时，索引遵循 `.gitignore`；否则回退为目录遍历
- PostgreSQL：
  - 默认使用 `pgserver==0.1.4` wheel（`backend/requirements-local.txt`）
  - 显式回退（`pg_ctl`）：设置 `LOCAL_PG_BIN_DIR` 指向包含 `initdb.exe` / `pg_ctl.exe` 的 PostgreSQL 16 `bin` 目录，并传 `--pg-backend pg_ctl`
- 一个可用的 LLM API Key（首次启动向导默认智谱 `zhipu` / `glm-4.7-flash`）

## 2. 安装与启动

```powershell
cd backend
py -3.12 -m venv .venv      # 没有 py launcher 时改用：python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -r requirements-local.txt

cd ..\frontend
npm ci
npm run build

cd ..\backend
python nova.py local
```

启动成功后终端输出一行 JSON（默认使用随机空闲端口）：

```json
{"event": "listening", "url": "http://127.0.0.1:54321"}
```

用浏览器打开该 URL。首次启动且尚未配置项目或 Key 时会弹出向导：填写项目文件夹绝对路径、厂商、模型与 API Key（默认 `zhipu` / `glm-4.7-flash`）。Key 已保存过时再次打开可留空。

可选参数：

```powershell
python nova.py local --port 8000          # 固定端口（默认 0 = 随机空闲端口）
python nova.py local --pg-backend pg_ctl  # 使用系统 PostgreSQL 二进制
python nova.py local --config D:\Nova\nova-config.json
python nova.py local --host 127.0.0.1     # 仅允许回环地址
```

> 不要直接用 `uvicorn app.main:app` 启动本地模式：本地启动器负责生成/注入 `SECRET_KEY`、数据目录与 PostgreSQL DSN。

## 3. 数据目录与密钥

默认配置与数据都在 `%APPDATA%\Nova`（可用 `--config` 或 `NOVA_CONFIG_PATH` 改配置位置，用配置中的 `dataDir` 改数据目录）：

| 路径 | 内容 |
|---|---|
| `nova-config.json` | `secretKey`（JWT 与 Fernet 加密的主密钥）、`dataDir`、`pgBackend`、`allowInstallDeps`，以及 `version` / `mode` 与默认空的 `serverUrl`、`updateUrl` |
| `pgdata/` | 本地 PostgreSQL 数据目录（`pgserver` 或 `pg_ctl`）；`pg_ctl` 后端的服务端日志与命令输出在 `pgdata/postgres.log`、`pgdata/pg_ctl.log` |
| `logs/` | 本地模式只输出到终端，不写文件日志（目录可能为空） |
| `tmp/` | `run_code` 与验证的临时工作区，任务结束清理 |
| `users/`、`skills/`、`legacy-repos/`、`downloads/`、`mcp.json` | 其他本地数据（用户文件、技能、旧仓库、下载、MCP 配置） |

API Key 只写入 PostgreSQL 的 `user_llm_providers.api_key_enc`（由 `secretKey` 派生的 Fernet 密钥加密）；接口只返回 `has_key` 或掩码提示，不回传明文。

`nova-config.json` 不要提交或发给别人；仓库 `.gitignore` 已忽略常见的误放位置 `backend/nova-config.json`。

## 4. 安全边界（必读）

- 服务只绑定回环地址（`127.0.0.1` / `localhost` / `::1`），不监听局域网；启动器会拒绝其他 host。
- 本地模式没有登录页，也没有容器隔离：命令以当前 Windows 用户身份在项目目录直接执行。
- 四档权限仍然生效：
  - `readonly`（计划模式）：拒绝 `run_command` / `run_code`，并拦截所有写入/执行类工具。
  - `ask`（变更前确认 / 每步问我）：每次写入、`run_command` / `run_code` 都需要审批，批准后才真实执行。
  - `auto` / `full`：按现有策略放行；危险命令与 `git push` 仍在策略层拒绝。
- HostExecutor 使用环境变量白名单（只保留 `PATH`、系统变量等），剥离 `*_KEY`、`*_TOKEN`、`*SECRET*`、`*PASSWORD*`、`*CREDENTIAL*`、`AWS_*` / `GOOGLE_*` / `AZURE_*`、`DATABASE_URL` 等敏感变量；命令工作目录与文件工具路径都被限制在项目根目录内（解析符号链接 / junction 后再校验）。
- `install_deps` 默认禁用。只有把 `%APPDATA%\Nova\nova-config.json` 的 `"allowInstallDeps"` 改为 `true`（或启动前在 shell 设置 `LOCAL_ALLOW_INSTALL_DEPS=true`）并重启后，才会在非 `readonly` 模式下按次审批执行；Python 依赖要求项目根目录已有 `.venv`（或 `venv`）且包含 pip，否则报“未找到项目虚拟环境 .venv…”；Node 依赖要求根目录 `package.json`。`readonly` 始终拒绝。
- 本地检索不启用 Qdrant / embedding，使用关键词 + 符号检索；引用仍是 `文件:行号`，证据校验逻辑不变。
- 验证与修复任务在主机临时工作区运行：工作区的“验证”按钮对 Python 项目可用，Node / fullstack 项目在本地模式返回 `unsupported`（步骤标记 `skipped`）；“任务”视图中的修复任务（红-绿）以 Python / pytest 仓库为准。点击验证按钮即视为批准主机执行。
- `GET /api/v1/status/mode` 返回 `mode: local`、`auth: none`、`isolation: none`、`semantic_search: false`、`jobs_concurrency: 1` 与 `data_dir`；`GET /api/v1/status/health` 的 `qdrant` / `embedding` 显示 `disabled: local mode`。

## 5. 退出与残留检查

按 `Ctrl+C` 退出。启动器按 “uvicorn → job runner → PostgreSQL” 顺序收尾；PostgreSQL 是否停止以 `postmaster.pid` 验证，必要时用 `taskkill /T /F` 清理进程树。

```powershell
Get-Process postgres -ErrorAction SilentlyContinue
Get-Process python -ErrorAction SilentlyContinue
```

两条命令都不应再显示 Nova 启动的进程（`python` 可能列出你另外运行的脚本，请按命令行确认）。若 PostgreSQL 残留，先查看启动终端输出；`pg_ctl` 后端的日志在 `pgdata\postgres.log` 与 `pgdata\pg_ctl.log`。下一次启动会识别 stale PID 并清理；无法确认进程身份时会拒绝终止该进程并保留数据目录，但启动失败信息只显示异常类型（如 `RuntimeError`），请手动确认 `pgdata\postmaster.pid` 中的进程后再处理。

同一数据目录同时只允许一个 Nova 实例：重复启动会在 PostgreSQL 启动前因实例锁失败。

## 6. 故障排查

| 现象 | 处理 |
|---|---|
| `pgserver 未安装` | 安装 `backend/requirements-local.txt`，或改用 `--pg-backend pg_ctl` |
| `找不到 initdb` | 设置 `LOCAL_PG_BIN_DIR` 到 PostgreSQL 16 的 `bin` 目录 |
| 安装依赖提示“未找到项目虚拟环境 .venv” | Python 依赖安装要求项目根目录已有 `.venv`（或 `venv`）且包含 pip；先在项目目录创建虚拟环境后重试 |
| 启动即退出，提示 SECRET_KEY | 必须用 `python nova.py local`，不要直接 `uvicorn app.main:app` |
| 首次向导提示没有 API Key | 填写 Key 后重试；已保存过可留空 |
| 搜索只有关键词结果 | 本地模式预期行为；health 会显示 `qdrant: disabled: local mode` |
| 端口冲突 | 不传 `--port` 使用随机端口 |
| 想重置本地数据库 | 退出后删除 `%APPDATA%\Nova\pgdata`；只重置数据库，`users/`、`skills/`、`downloads/`、`legacy-repos/`、`mcp.json` 与你的项目文件都会保留 |
| 验证返回 `unsupported` | Node / fullstack 项目本地暂不支持，改用服务器模式或手动执行 |
| pgserver 异常退出后无法重启 | 启动器会自动用同一数据目录尝试 `pg_ctl` 回退（使用 pgserver 自带或 `LOCAL_PG_BIN_DIR` 指定的二进制）；失败时数据目录会保留，按错误提示处理后重试，不要删除数据目录 |
| 提示已有实例在运行 | 关闭另一个 `nova.py local` 进程；实例锁文件为数据目录旁的 `.nova-instance.lock` |
| API Key 无法解密 | `secretKey` 已变化（例如删除/重建了 `nova-config.json`）；重新保存 Key |
| 项目路径被拒绝 | 必须是本机绝对路径，且既不能包含、也不能位于 Nova 数据目录内；不支持 UNC / 设备路径与磁盘根目录 |

## 7. 与云端模式的关系

`NOVA_MODE` 默认 `server`，云端 Docker Compose 部署完全不变。本地模式不修改 `docker-compose.yml`、不安装 Qdrant、不启用 Docker 沙箱、不启用账号体系。云端升级仍由 `AUTO_INIT_DB=true` 自动执行 versioned migrations（当前最高为 18）。

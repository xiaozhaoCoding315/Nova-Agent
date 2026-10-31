# Nova Agent Phase 2：本地运行时 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变云端模式行为的前提下，让同一个 FastAPI 后端以 `NOVA_MODE=local` 在 Windows 11 本机运行：内嵌 PostgreSQL、固定本地用户、本地文件夹项目索引、无容器 HostExecutor、无 Qdrant 的检索降级、单 worker 后台任务，以及首次启动 API。

**Architecture:** `NOVA_MODE` 是唯一模式开关，默认 `server`，所有派生行为由 `Settings` 上的显式属性决定（`is_local` / `use_host_executor` / `use_embeddings` / `effective_job_max_concurrency`）。本地启动器在导入 `app.main` **之前**读取 `%APPDATA%/Nova/nova-config.json`、生成并设置 `SECRET_KEY` 等环境变量、拉起内嵌 PostgreSQL（`pgserver` 或 `pg_ctl` 两种后端），再把 `POSTGRES_DSN_OVERRIDE` 注入环境后启动 uvicorn；退出时按 “uvicorn → job runner → PostgreSQL” 顺序清理。本地项目只登记用户现有目录（不复制、不在删除时删用户文件），HostExecutor 在项目根目录执行真实命令，策略与审批复用现有 `decide_tool`。

**Tech Stack:** Python 3.12 / FastAPI / psycopg3 / PostgreSQL 16 / pytest；React 18 / TypeScript / Vite / Zustand；内嵌 PostgreSQL 候选 `pgserver` 或官方 `pg_ctl` 二进制；Windows 进程管理 `taskkill /T /F`。

## Global Constraints

- `NOVA_MODE=server` 是默认值。未设置该变量时，云端登录、游客、注册、配额、管理员、Docker 沙箱、Qdrant 检索行为必须逐字节等价；每个模式分支都必须有显式单元测试或契约测试。
- 本地模式不发送遥测、不上传仓库内容、不访问 Nova 服务器；唯一允许的外部请求是用户自己配置的 LLM API。
- 本地模式必须满足设计文档原文：“断网（除 LLM API）可用；不访问 Nova 服务器。”“退出后 PostgreSQL 与 uvicorn 进程干净停止。”
- 密钥只能存在于 `user_llm_providers.api_key_enc`（Fernet 加密，主密钥来自本机 `nova-config.json`）或本地 gitignored 配置文件；不得写入日志、trace、SSE、错误消息、审计详情或 API 响应。API 只返回 `has_key: true/false`。
- 本地执行必须明示“无容器隔离”：工具结果含 `"isolation": "none"`、`"sandboxed": false` 和中文 warning；前端页脚显示“本地模式 · 无容器隔离”。
- Windows 11 是 v1 验收平台；代码保持跨平台（POSIX 使用 `start_new_session` + `killpg`），但 Phase 2 不制作 macOS/Linux 安装包。
- 不实现 Phase 3 的 UI 重设计，不实现 Phase 4 的 Electron/NSIS/自动更新；前端只做本地模式必需的最小改动。
- 不引入 SQLite、SQLAlchemy、React 19、Pydantic v1；`docker-compose.yml` 与云端 Dockerfile 不修改。内嵌 PG 依赖只放在 `requirements-local.txt`（若 spike 选择 `pgserver`），云端镜像不安装。
- 每个 Task 结束必须独立通过目标测试、`ruff check app tests`、`python -m scripts.export_openapi --check`；任何 OpenAPI 变更必须在同一提交内执行 `python -m scripts.export_openapi` 和 `npm run contract:generate`。
- 基线：`NOVA_TEST_FAST=1 python -m pytest tests -q` = **589 passed, 7 skipped**（596 collected）。新增本地集成测试默认 skip，CI 不得因缺少 PostgreSQL/Qdrant/Docker 而失败。
- `docs/superpowers/` 被 `.gitignore` 忽略；提交本计划或 spike 结果时需要 `git add -f docs/superpowers/...`。实现代码按正常 `git add`。
- 提交信息使用 `feat:` / `fix:` / `test:` / `docs:` / `chore:`；每个 Task 一个提交（Task 0 允许一个 docs 提交）。

---

## File Structure

### 新建

| 文件 | 职责 |
|---|---|
| `backend/app/local/__init__.py` | 本地运行时包标记 |
| `backend/app/local/config.py` | `nova-config.json` 定位、创建、原子写入、`SECRET_KEY` 生成、`runtime_env()`、脱敏视图 |
| `backend/app/local/pg.py` | `LocalPostgres`、`PgInfo`、pgserver/pg_ctl 后端、stale PID 清理、DSN 构造、幂等 stop |
| `backend/app/local/runtime.py` | 本地设置校验（数据目录、强 SECRET_KEY、loopback） |
| `backend/app/local/launcher.py` | 先启 PG 再导入 app，选择随机端口，uvicorn 运行，finally 停 PG |
| `backend/app/local/projects.py` | 本地路径校验、项目登记、重复登记去重、入队索引 |
| `backend/app/core/exec/__init__.py` | 执行器包标记 |
| `backend/app/core/exec/host.py` | 路径 jail、环境剥离、项目 venv 探测、进程启动/流式输出/超时/整树取消、host PID 注册表 |
| `backend/app/core/exec/service.py` | `run_command_host` / `run_code_host` / `run_staged_host` 的临时目录与清理 |
| `backend/app/core/indexing/retry.py` | 本地维护循环的卡住索引重试 |
| `backend/app/api/v1/local_setup.py` | `GET/POST /local/setup`，仅本地模式 |
| `backend/requirements-local.txt` | 仅在 Task 0 判定 A 时安装 `pgserver==0.1.4`；云端镜像不读取 |
| `backend/tests/test_local_config.py` | 配置创建、权限、无 Key、原子写、脱敏 |
| `backend/tests/test_local_pg.py` | stale PID、DSN、幂等 stop；真实 PG 集成测试默认 skip |
| `backend/tests/test_local_launcher.py` | 环境注入、loopback 限制、PG 启停顺序、随机端口 |
| `backend/tests/test_local_auth.py` | 本地用户、无 Cookie 绕过、非本地 404、配额绕过 |
| `backend/tests/test_local_projects.py` | 绝对路径/UNC/根目录/数据目录/符号链接校验、去重、删除不删用户文件、gitignore |
| `backend/tests/test_host_executor.py` | 环境剥离、路径 jail、shell 参数、真实执行、超时、整树取消、host 取消注册表 |
| `backend/tests/test_host_tools.py` | run_command/run_code 本地分支、结果标记、临时目录清理、sandbox_status |
| `backend/tests/test_local_verify.py` | 本地 verify 与 task 红绿、install_deps 禁用/批准路径 |
| `backend/tests/test_local_retrieval.py` | 无 dense 检索、health/mode、init_all skip Qdrant |
| `backend/tests/test_local_jobs.py` | 单 worker 上限、维护循环裁剪、索引重试 |
| `backend/tests/test_local_setup.py` | 首次启动状态、保存 Key/项目、响应不回显 Key、非本地 404 |
| `frontend/src/stores/mode.ts` | 模式与首次启动状态 store |
| `frontend/src/components/LocalSetupDialog.tsx` | 首次启动：项目绝对路径 + 厂商/模型/Key |
| `frontend/src/components/LocalFolderDialog.tsx` | 工作区“打开本地文件夹”对话框（路径输入，Phase 4 换原生选择器） |
| `docs/LOCAL_MODE.md` | 本地模式启动、数据目录、安全边界、故障排查 |
| `docs/superpowers/plans/2026-10-31-phase2-spike-results.md` | Task 0 的环境、命令、结果、go/no-go 决策与证据 |

### 修改

| 文件 | 改动 |
|---|---|
| `backend/app/config.py` | `NOVA_MODE`、本地路径/PG/安装开关、DSN override、`is_local`/`use_host_executor`/`use_embeddings`/`effective_job_max_concurrency`/`data_root`/`local_tmp_root` |
| `backend/app/main.py` | 本地启动校验；本地维护分支；本地静态前端托管；关机顺序 |
| `backend/app/db/init_db.py` | `ensure_database(admin_dsn, dbname)` 参数化；migration 18 `repos.origin`；本地跳过 Qdrant/legacy storage、seed 本地用户 |
| `backend/app/core/security/auth.py` | `ensure_local_user` / `get_local_user`、`get_current_user` 本地分支、`require_admin` 本地分支 |
| `backend/app/core/security/limits.py` | 本地模式跳过配额/限流/token 预算 |
| `backend/app/api/v1/auth.py` | 除 `/auth/me`、`/auth/config` 外的账号路由在本地返回 404 |
| `backend/app/models/schemas.py` | `RepoLocalCreate`、`RepoOut.origin`、`ModeOut`、`LocalSetup*` |
| `backend/app/api/v1/repos.py` | `POST /repos/local` |
| `backend/app/api/v1/router.py` | 注册 `local_setup` router |
| `backend/app/api/v1/status.py` | `/status/mode`；本地 health 不把 Qdrant/embedding 判为失败 |
| `backend/app/core/indexing/pipeline.py` | `create_repo_row(origin=...)`、`create_local_repo_row`、`get_repo/list_repos` 返回 origin、本地索引 walker、删除保护 |
| `backend/app/core/indexing/walker.py` | `iter_local_project_files`（`git ls-files --cached --others --exclude-standard` + walk 回退 + 符号链接逃逸拦截） |
| `backend/app/core/sandbox/runtime.py` | `sandbox_status` 本地分支；`kill_job_containers` 本地转 HostExecutor 注册表 |
| `backend/app/core/tools/run_command.py` | 本地分支执行真实项目根目录命令 |
| `backend/app/core/tools/run_code.py` | 本地分支写入数据目录临时工作区执行 |
| `backend/app/core/tools/install_deps.py` | 本地默认禁用；显式开启后走项目 `.venv`/npm + 审批 |
| `backend/app/core/security/policy.py` | 本地 install_deps 门禁与审批 |
| `backend/app/core/verify/service.py` | 本地 `_run_verification_host` |
| `backend/app/core/tasks/engine.py` | 本地跳过 sandbox 可用性检查；`_sandbox_run` 走 host 临时工作区 |
| `backend/app/core/rag/dense.py` / `retriever.py` | `use_embeddings=false` 时短路 dense |
| `backend/app/core/jobs/runner.py` | 全局 worker 上限 `effective_job_max_concurrency` |
| `backend/app/core/agent/loop.py` | 本地隐藏 bridge 工具（`local_available=False`） |
| `backend/nova.py` | `nova.py local` 子命令 |
| `backend/.env.example` | 增加注释化的本地开关，默认不改变云端 |
| `.gitignore` | 忽略仓库内可能误放的 `backend/nova-config.json`、`backend/local-data/` |
| `frontend/src/lib/types.ts` | `ModeInfo`、`LocalSetup*`、`Repo.origin` |
| `frontend/src/lib/api.ts` | `status.mode`、`repos.localFolder`、`local.setupStatus/setup` |
| `frontend/src/App.tsx` | 加载模式；本地隐藏游客横幅/配额；页脚无隔离提示；首次启动弹窗 |
| `frontend/src/views/SettingsView.tsx` | 本地隐藏 usage/account/admin 区块 |
| `frontend/src/views/WorkspaceView.tsx` | “打开本地文件夹”入口与对话框 |
| `README.md` / `docs/DEPLOY.md` | 本地模式入口与云端不变声明；修正“绝不降级”表述 |
| `contracts/openapi.json` / `frontend/src/lib/api-schema.d.ts` | 每次后端 schema 变更后重新生成 |

---

## Task 0: 一日打包/运行时 Spike（go/no-go 门）

**Files:**
- Create: `docs/superpowers/plans/2026-10-31-phase2-spike-results.md`
- Modify: 本计划 Task 0 复选框与“决策记录”小节
- Test: 临时目录脚本，不进入仓库

**Interfaces:**
- Consumes: 设计文档 Phase 2“先做 1 天打包 spike：PyInstaller + pgserver + tree-sitter 原生依赖；失败则回退内置 Python 运行时 + venv”。
- Produces: `local_pg_backend` 默认值（`pgserver` 或 `pg_ctl`）、Phase 4 打包路线（PyInstaller 或 bundled runtime）、明确 go/no-go。

> **这是决策点，不是成功假设。** 超时一天。即使 spike 失败，Phase 2 仍可继续：Task 3 抽象出两种 PG 后端；失败只改变默认后端与 Phase 4 打包路线。

- [x] **Step 1: 记录环境**

在 Windows 11 上运行并粘贴到 spike 结果文档：

```bash
python --version
py -0p
systeminfo | grep -i "OS Name\|OS Version"
where.exe git
where.exe pg_ctl 2>/dev/null || echo "pg_ctl not on PATH"
```

Expected: `Python 3.12.x`；`git` 可用；`pg_ctl` 可能存在也可能不存在（不存在不影响 A 路线）。

- [x] **Step 2: 在仓库外创建一次性 venv**

```bash
cd "$TEMP"
py -3.12 -m venv nova-pg-spike
source nova-pg-spike/Scripts/activate
python -m pip install --upgrade pip
pip index versions pgserver
```

Expected: 输出可用版本。已知 0.1.4（2024-06）是最后版本；若命令无结果或报错，直接记 **pgserver = NO-GO**。

- [x] **Step 3: 验证 Windows cp312 wheel**

```bash
pip download pgserver==0.1.4 --only-binary=:all: -d "$TEMP/nova-pg-wheels"
ls "$TEMP/nova-pg-wheels"
```

Expected（A 路线唯一可接受结果）：出现 `pgserver-0.1.4-...win_amd64.whl` 或 `...win_amd64...whl`。

若输出 `ERROR: Could not find a version that satisfies the requirement pgserver==0.1.4` 或只下载到 `manylinux`/`macosx` wheel，记录 **pgserver = NO-GO**，跳到 Step 5。

- [x] **Step 4: 验证 TCP、psycopg3、建库、持久化、干净停止**

```bash
pip install pgserver==0.1.4 "psycopg[binary]==3.2.3"
cat > "$TEMP/spike_pg.py" <<'PY'
import pathlib, tempfile, time
import pgserver, psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo

data = pathlib.Path(tempfile.mkdtemp(prefix="nova-pg-")) / "pgdata"
srv = pgserver.get_server(str(data))
uri = srv.get_uri()
print("URI", uri.replace(uri.split("@")[0], "<redacted>") if "@" in uri else uri)
params = conninfo_to_dict(uri)
print("HOST_KIND", "tcp" if params.get("host", "").startswith(("127.", "localhost")) else "socket-or-empty")
print("PORT", params.get("port"))
with psycopg.connect(uri, connect_timeout=5) as conn:
    print("VERSION", conn.execute("select version()").fetchone()[0][:40])
with psycopg.connect(uri, connect_timeout=5, autocommit=True) as conn:
    conn.execute("create database nova_probe")
probe = make_conninfo(uri, dbname="nova_probe")
with psycopg.connect(probe, connect_timeout=5) as conn:
    print("DB_OK", conn.execute("select 1").fetchone()[0])
srv.cleanup()
print("CLEANED", data.exists())
time.sleep(2)
PY
python "$TEMP/spike_pg.py"
```

Expected: 打印 `VERSION PostgreSQL 16...` 和 `DB_OK 1`。`HOST_KIND` 必须是 `tcp`，否则 Windows 上 psycopg 无法连接，记 **pgserver = NO-GO**。

```bash
tasklist | grep -i postgres || echo "no postgres process"
```

Expected: `no postgres process`。若仍残留，记 **pgserver = NO-GO**（不满足“退出后干净停止”）。

- [x] **Step 5: 验证官方 PostgreSQL 二进制回退（B 路线）**

若本机没有 PG 二进制，从官方 Windows x64 ZIP 解压到 `%TEMP%/pgsql`，然后：

```bash
"$TEMP/pgsql/bin/initdb.exe" -D "$TEMP/nova-pgctl/pgdata" -U nova --auth=scram-sha-256 --pwfile="$TEMP/pgpass.txt" -E UTF8
"$TEMP/pgsql/bin/pg_ctl.exe" -D "$TEMP/nova-pgctl/pgdata" -l "$TEMP/nova-pgctl/postgres.log" -o "-p 55432 -h 127.0.0.1" -w start
"$TEMP/pgsql/bin/psql.exe" "postgresql://nova:<password>@127.0.0.1:55432/postgres" -c "select version()"
"$TEMP/pgsql/bin/pg_ctl.exe" -D "$TEMP/nova-pgctl/pgdata" -m fast -w stop
tasklist | grep -i postgres || echo "no postgres process"
```

Expected: psql 输出版本；stop 后无 postgres 进程。该路线通过则 B 可行。

- [x] **Step 6: 验证 PyInstaller + pgserver + tree-sitter**

在 spike venv 中：

```bash
pip install "pyinstaller==6.10.0" "fastapi==0.115.0" \
    "tree-sitter==0.26.0" "tree-sitter-python==0.25.0" "tree-sitter-typescript==0.23.2" \
    "tree-sitter-go==0.25.0" "tree-sitter-java==0.23.5" "tree-sitter-rust==0.24.2"
cat > "$TEMP/spike_main.py" <<'PY'
import pathlib, tempfile
import fastapi, psycopg, tree_sitter, tree_sitter_python
print("imports-ok", fastapi.__version__, psycopg.__version__)
try:
    import pgserver
    data = pathlib.Path(tempfile.mkdtemp(prefix="nova-exe-pg-")) / "pgdata"
    srv = pgserver.get_server(str(data))
    print("embedded-pg-ok", bool(srv.get_uri()))
    srv.cleanup()
except Exception as exc:
    print("embedded-pg-failed", type(exc).__name__, str(exc)[:200])
PY
pyinstaller --onefile --name nova-spike \
  --collect-all pgserver --collect-all tree_sitter \
  --collect-all tree_sitter_python --collect-all tree_sitter_typescript \
  --collect-all tree_sitter_go --collect-all tree_sitter_java --collect-all tree_sitter_rust \
  "$TEMP/spike_main.py"
"$TEMP/dist/nova-spike.exe"
```

Expected: `imports-ok` 且 `embedded-pg-ok True`。若 `embedded-pg-failed`，PyInstaller + pgserver 路线不可行，但 pg_ctl + bundled Python runtime 仍可继续。

注：上面的依赖版本是 `backend/requirements.txt` 的应用 pin，`--collect-all` 覆盖 `backend/app/core/indexing/symbols.py`
实际导入的全部 grammar（Python 符号提取本身走 `ast`）。Task 0 实跑时只安装了 `tree-sitter==0.23.2` /
`tree-sitter-python==0.23.6` 并只打包 `tree_sitter_python`（见结果文档）；其余 grammar 与 0.26.0 组合未验证。

- [x] **Step 7: 写出 go/no-go 决策**

把以下矩阵和实测证据写入 `docs/superpowers/plans/2026-10-31-phase2-spike-results.md`：

```markdown
# Phase 2 Runtime Spike Results

- 日期：
- Windows / Python / CPU：
- pgserver 版本与 wheel tag：
- pgserver TCP + psycopg + create database：PASS/FAIL（证据：）
- pgserver cleanup 后无 postgres 进程：PASS/FAIL（证据：）
- pg_ctl 回退：PASS/FAIL（证据：）
- PyInstaller imports：PASS/FAIL（证据：）
- PyInstaller + pgserver 启动：PASS/FAIL（证据：）
- tree-sitter 原生扩展：PASS/FAIL（证据：）
- 本机未安装/未运行 Qdrant，且不依赖 Qdrant 服务（证据：`tasklist | grep -i qdrant` 无输出；Task 10 据此实现无 Qdrant 检索）

## 决策

- `local_pg_backend` 默认值：pgserver | pg_ctl
- Phase 4 打包：PyInstaller | bundled Python runtime + venv
- 是否继续 Phase 2：GO | NO-GO（仅当 PostgreSQL 本身无法在目标机器运行时才 NO-GO）
- 后续 Task 3 必须采用的路径：
```

- [x] **Step 8: 提交 spike 结果**

```bash
git add -f docs/superpowers/plans/2026-10-31-phase2-spike-results.md docs/superpowers/plans/2026-10-31-phase2-local-runtime.md
git commit -m "docs: record phase 2 local runtime spike decision"
```

Expected: commit 成功；不修改任何 `backend/` 或 `frontend/` 文件。

**决策后果（写入计划后再继续）：**
- A（pgserver 全 PASS）：Task 3 默认 `LOCAL_PG_BACKEND=pgserver`；新增 `backend/requirements-local.txt` 固定 `pgserver==0.1.4`。
- B（pgserver FAIL、pg_ctl PASS）：Task 3 默认 `pg_ctl`；不新增 pgserver 依赖；Phase 4 采用 bundled Python runtime + venv + PostgreSQL ZIP 二进制。
- C（PostgreSQL 无法运行）：停止，回到设计评审；不得用 SQLite 替代。

**决策记录（2026-11-01，实测见 `2026-10-31-phase2-spike-results.md`）：**
- 结果：A 路线全部 PASS，B 路线也 PASS（官方 PostgreSQL 16.2 ZIP + `pg_ctl` 可运行且干净停止）。
- `local_pg_backend` 默认值：`pgserver`；`pg_ctl` 保留为显式回退后端。
- Phase 4 打包：PyInstaller `--onefile`；`--collect-all` 覆盖 `pgserver` 与应用实际导入的全部 grammar：
  `--collect-all pgserver --collect-all tree_sitter --collect-all tree_sitter_python
  --collect-all tree_sitter_typescript --collect-all tree_sitter_go --collect-all tree_sitter_java
  --collect-all tree_sitter_rust`。
  spike 只打包了 toy `spike_main.py`（`embedded-pg-ok True`），未验证 `app.main`/uvicorn 应用级打包、
  杀毒/SmartScreen、`--onefile` 启动延迟、Electron/NSIS 集成与完整 hidden-import 集；
  tree-sitter 实测版本 0.23.2 / 0.23.6 与应用 pin（0.26.0 / 0.25.0 及其余 grammar）不同。
- Phase 2：GO。Task 3 采用 A 路径，新增 `backend/requirements-local.txt` 固定 `pgserver==0.1.4`。

---

## Task 1: `NOVA_MODE` 与派生能力开关

**Files:**
- Modify: `backend/app/config.py`
- Test: `backend/tests/test_config.py`

**Interfaces:**
- Consumes: 现有 `Settings` 单例、`postgres_dsn` / `postgres_admin_dsn`。
- Produces: `settings.is_local: bool`、`settings.use_host_executor: bool`、`settings.use_embeddings: bool`、`settings.effective_job_max_concurrency: int`、`settings.data_root: Path`、`settings.local_tmp_root: Path`、`settings.postgres_dsn_override`、`settings.embeddings_enabled`、`settings.job_max_concurrency`。

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_config.py` 末尾追加：

```python
import pytest


def test_local_mode_derived_flags():
    s = _fresh(nova_mode="local", nova_data_dir="C:/NovaData")
    assert s.is_local is True
    assert s.use_host_executor is True
    assert s.use_embeddings is False
    assert s.effective_job_max_concurrency == 1


def test_server_mode_defaults_are_unchanged():
    s = _fresh()
    assert s.nova_mode == "server"
    assert s.is_local is False
    assert s.use_host_executor is False
    assert s.use_embeddings is True
    assert s.effective_job_max_concurrency == 0


def test_local_mode_requires_data_dir():
    s = _fresh(nova_mode="local", nova_data_dir="")
    with pytest.raises(RuntimeError, match="NOVA_DATA_DIR"):
        _ = s.data_root


def test_local_tmp_root_defaults_under_data_dir():
    s = _fresh(nova_mode="local", nova_data_dir="C:/NovaData")
    assert s.local_tmp_root == s.data_root / "tmp"


def test_dsn_override_switches_database_names():
    from psycopg.conninfo import conninfo_to_dict

    s = _fresh(
        postgres_dsn_override="postgresql://nova:pw@127.0.0.1:55432/nova_agent?connect_timeout=3"
    )
    assert s.postgres_dsn == (
        "postgresql://nova:pw@127.0.0.1:55432/nova_agent?connect_timeout=3"
    )
    admin = conninfo_to_dict(s.postgres_admin_dsn)
    assert admin["dbname"] == "postgres"
    assert admin["port"] == 55432
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && NOVA_TEST_FAST=1 python -m pytest tests/test_config.py -q`

Expected: FAIL — `Settings` 没有 `nova_mode` 字段，报 `ValidationError` 或 `AttributeError`。

- [ ] **Step 3: 实现最小配置**

在 `backend/app/config.py` 顶部导入：

```python
from pathlib import Path
from typing import Literal
```

在 `Settings` 内、`# ---------- App ----------` 之前加入：

```python
    # ---------- Local runtime ----------
    # server = 现有云端行为；local = 本机单用户运行时。
    nova_mode: Literal["server", "local"] = "server"
    nova_data_dir: str = ""
    local_user: str = "local"
    local_tmp_dir: str = ""
    local_pg_backend: Literal["pgserver", "pg_ctl"] = "pgserver"
    local_pg_bin_dir: str = ""
    local_pg_port: int = 0
    local_allow_install_deps: bool = False
    postgres_dsn_override: str = ""
    embeddings_enabled: bool = True
    job_max_concurrency: int = 0     # 0 = 沿用各 kind 自己的并发上限
```

在 `Settings` 属性区末尾加入：

```python
    @property
    def is_local(self) -> bool:
        return self.nova_mode == "local"

    @property
    def use_host_executor(self) -> bool:
        """Local mode runs commands on the host; cloud mode keeps Docker."""
        return self.is_local

    @property
    def use_embeddings(self) -> bool:
        """Local v1 has no Qdrant/embedding; cloud keeps dense retrieval."""
        return self.embeddings_enabled and not self.is_local

    @property
    def effective_job_max_concurrency(self) -> int:
        """0 = no global cap (existing per-kind limits); local = single worker."""
        return 1 if self.is_local else self.job_max_concurrency

    @property
    def data_root(self) -> Path:
        if not self.nova_data_dir:
            raise RuntimeError("NOVA_DATA_DIR is required when NOVA_MODE=local")
        return Path(self.nova_data_dir).expanduser().resolve()

    @property
    def local_tmp_root(self) -> Path:
        if self.local_tmp_dir:
            return Path(self.local_tmp_dir).expanduser().resolve()
        return self.data_root / "tmp"

    @staticmethod
    def _dsn_with_db(dsn: str, dbname: str) -> str:
        from psycopg.conninfo import conninfo_to_dict, make_conninfo

        params = conninfo_to_dict(dsn)
        params["dbname"] = dbname
        return make_conninfo(**params)
```

把现有两个 DSN 属性改为 override 优先：

```python
    @property
    def postgres_dsn(self) -> str:
        if self.postgres_dsn_override:
            return self.postgres_dsn_override
        return (f"postgresql://{self.postgres_user}:{self.postgres_password}"
                f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
                f"?connect_timeout=3")

    @property
    def postgres_admin_dsn(self) -> str:
        """DSN against the maintenance DB, used to CREATE DATABASE on first run."""
        if self.postgres_dsn_override:
            return self._dsn_with_db(self.postgres_dsn_override, "postgres")
        return (f"postgresql://{self.postgres_user}:{self.postgres_password}"
                f"@{self.postgres_host}:{self.postgres_port}/postgres"
                f"?connect_timeout=3")
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && NOVA_TEST_FAST=1 python -m pytest tests/test_config.py -q`

Expected: PASS，包含新增 5 个测试。

- [ ] **Step 5: 云端回归与 lint**

Run: `cd backend && NOVA_TEST_FAST=1 python -m pytest tests -q`

Expected: `589 passed, 7 skipped`（新增测试在 test_config.py 内，数量变为 594 passed / 7 skipped；不允许 failed）。

Run: `cd backend && ruff check app tests`

Expected: `All checks passed!`

- [ ] **Step 6: 提交**

```bash
git add backend/app/config.py backend/tests/test_config.py
git commit -m "feat: add NOVA_MODE and local runtime capability flags"
```

---

## Task 2: 本地配置文件、数据目录与主密钥

**Files:**
- Create: `backend/app/local/__init__.py`
- Create: `backend/app/local/config.py`
- Modify: `.gitignore`
- Test: `backend/tests/test_local_config.py`

**Interfaces:**
- Consumes: 无（独立模块，不导入 `app.config`，确保可在设置单例创建前运行）。
- Produces:
  - `default_config_path(platform: str | None = None, env: Mapping[str, str] | None = None) -> Path`
  - `load_or_create(path: str | Path | None = None) -> dict`
  - `runtime_env(config: dict, *, data_dir: Path | None = None) -> dict[str, str]`
  - `redacted_config(config: dict) -> dict`
  - 配置字段：`version`、`mode`、`serverUrl`、`dataDir`、`secretKey`、`updateUrl`、`pgBackend`、`allowInstallDeps`。

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_local_config.py`：

```python
import json
import os

import pytest

from app.local.config import (
    default_config_path,
    load_or_create,
    redacted_config,
    runtime_env,
)


def test_default_config_path_windows(monkeypatch):
    p = default_config_path(
        platform="win32",
        env={"APPDATA": "C:/Users/alice/AppData/Roaming"},
    )
    assert str(p).replace("\\", "/").endswith("Nova/nova-config.json")


def test_default_config_path_respects_override():
    p = default_config_path(
        platform="win32",
        env={"NOVA_CONFIG_PATH": "D:/Nova/nova-config.json", "APPDATA": "C:/x"},
    )
    assert str(p).replace("\\", "/").endswith("Nova/nova-config.json")


def test_load_or_create_generates_secret_and_data_dir(tmp_path):
    path = tmp_path / "Nova" / "nova-config.json"
    cfg = load_or_create(path)
    assert path.is_file()
    assert cfg["version"] == 1
    assert cfg["mode"] == "local"
    assert cfg["dataDir"] == str(path.parent)
    assert len(cfg["secretKey"]) >= 32
    assert "apiKey" not in json.dumps(cfg)
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["secretKey"] == cfg["secretKey"]


def test_load_or_create_is_stable(tmp_path):
    path = tmp_path / "nova-config.json"
    first = load_or_create(path)
    second = load_or_create(path)
    assert first["secretKey"] == second["secretKey"]


def test_load_or_create_rejects_unknown_version(tmp_path):
    path = tmp_path / "nova-config.json"
    path.write_text(json.dumps({"version": 99}), encoding="utf-8")
    with pytest.raises(ValueError, match="version"):
        load_or_create(path)


def test_runtime_env_contains_no_secret_in_key_names_only(tmp_path):
    cfg = load_or_create(tmp_path / "nova-config.json")
    env = runtime_env(cfg)
    assert env["NOVA_MODE"] == "local"
    assert env["SECRET_KEY"] == cfg["secretKey"]
    assert env["NOVA_DATA_DIR"] == cfg["dataDir"]
    assert env["LOCAL_PG_DATA_DIR"].endswith("pgdata")
    assert env["EMBEDDINGS_ENABLED"] == "false"
    assert env["AUTO_INIT_DB"] == "true"
    assert env["APP_ENV"] == "local"
    assert "ZHIPU_API_KEY" not in env


def test_redacted_config_removes_secret(tmp_path):
    cfg = load_or_create(tmp_path / "nova-config.json")
    safe = redacted_config(cfg)
    assert "secretKey" not in safe
    assert safe["mode"] == "local"


@pytest.mark.skipif(os.name == "nt", reason="chmod is a no-op on Windows")
def test_config_file_is_private(tmp_path):
    path = tmp_path / "nova-config.json"
    load_or_create(path)
    assert (path.stat().st_mode & 0o777) == 0o600
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && NOVA_TEST_FAST=1 python -m pytest tests/test_local_config.py -q`

Expected: FAIL — `ModuleNotFoundError: No module named 'app.local'`。

- [ ] **Step 3: 实现配置模块**

创建空文件 `backend/app/local/__init__.py`。

创建 `backend/app/local/config.py`：

```python
"""Local desktop configuration. Never import app.config from this module.

The launcher must create the data dir and SECRET_KEY before the Settings
singleton is imported, so this module depends only on the standard library.
"""
import json
import os
import secrets
import sys
from collections.abc import Mapping
from pathlib import Path

CONFIG_VERSION = 1
FILENAME = "nova-config.json"


def default_config_path(
    platform: str | None = None,
    env: Mapping[str, str] | None = None,
) -> Path:
    env = env or os.environ
    override = env.get("NOVA_CONFIG_PATH")
    if override:
        return Path(override)
    plat = platform or sys.platform
    if plat == "win32":
        base = Path(env.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
    elif plat == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(env.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
    return base / "Nova" / FILENAME


def _atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def load_or_create(path: str | Path | None = None) -> dict:
    target = Path(path) if path else default_config_path()
    if target.exists():
        data = json.loads(target.read_text(encoding="utf-8"))
        if int(data.get("version", 0)) != CONFIG_VERSION:
            raise ValueError(f"unsupported nova-config version: {data.get('version')!r}")
        changed = False
        if not data.get("secretKey") or len(str(data["secretKey"])) < 32:
            data["secretKey"] = secrets.token_urlsafe(48)
            changed = True
        if not data.get("dataDir"):
            data["dataDir"] = str(target.parent)
            changed = True
        if "allowInstallDeps" not in data:
            data["allowInstallDeps"] = False
            changed = True
        if changed:
            _atomic_write(target, data)
        return data

    data = {
        "version": CONFIG_VERSION,
        "mode": "local",
        "serverUrl": "",
        "dataDir": str(target.parent),
        "secretKey": secrets.token_urlsafe(48),
        "updateUrl": "",
        "pgBackend": "pgserver",
        "allowInstallDeps": False,
    }
    _atomic_write(target, data)
    return data


def runtime_env(config: dict, *, data_dir: Path | None = None) -> dict[str, str]:
    data = Path(data_dir or config.get("dataDir") or "").expanduser().resolve()
    backend = str(config.get("pgBackend") or "pgserver")
    return {
        "NOVA_MODE": "local",
        "NOVA_DATA_DIR": str(data),
        "SECRET_KEY": str(config["secretKey"]),
        "USER_DATA_DIR": str(data / "users"),
        "REPOS_DIR": str(data / "legacy-repos"),
        "SKILLS_DIR": str(data / "skills"),
        "LOG_DIR": str(data / "logs"),
        "DOWNLOADS_DIR": str(data / "downloads"),
        "MCP_CONFIG_PATH": str(data / "mcp.json"),
        "LOCAL_TMP_DIR": str(data / "tmp"),
        "LOCAL_PG_DATA_DIR": str(data / "pgdata"),
        "LOCAL_PG_BACKEND": backend,
        "LOCAL_PG_BIN_DIR": str(config.get("pgBinDir") or os.environ.get("LOCAL_PG_BIN_DIR") or ""),
        "LOCAL_ALLOW_INSTALL_DEPS": (
            "true" if config.get("allowInstallDeps")
            or os.environ.get("LOCAL_ALLOW_INSTALL_DEPS", "").lower() in ("1", "true", "yes")
            else "false"
        ),
        "EMBEDDINGS_ENABLED": "false",
        "SANDBOX_ENABLED": "false",
        "MCP_ENABLED": "false",
        "AUTO_INIT_DB": "true",
        "JOB_RUNNER_ENABLED": "true",
        "APP_ENV": "local",
    }


def redacted_config(config: dict) -> dict:
    safe = dict(config)
    safe.pop("secretKey", None)
    return safe
```

在 `.gitignore` 的 Runtime data 段后加入：

```gitignore
# Local runtime config/data accidentally created inside the repo
backend/nova-config.json
backend/local-data/
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && NOVA_TEST_FAST=1 python -m pytest tests/test_local_config.py -q`

Expected: PASS，7 passed 或 6 passed + 1 skipped（Windows 上权限测试 skip 理由为 chmod no-op）。

- [ ] **Step 5: 全量回归与提交**

Run: `cd backend && NOVA_TEST_FAST=1 python -m pytest tests -q`

Expected: 全绿，无 failed。

```bash
git add backend/app/local/__init__.py backend/app/local/config.py backend/tests/test_local_config.py .gitignore
git commit -m "feat: add local config file and runtime environment"
```

---

## Task 3: 内嵌 PostgreSQL 生命周期（pgserver / pg_ctl 双后端）

**Files:**
- Create: `backend/app/local/pg.py`
- Create (仅当 Task 0 判定 A)：`backend/requirements-local.txt`
- Test: `backend/tests/test_local_pg.py`

**Interfaces:**
- Consumes: `Settings.local_pg_backend`、`local_pg_bin_dir`、`local_pg_port`、`settings.postgres_db`；Task 0 的后端决策。
- Produces:
  - `@dataclass(frozen=True) PgInfo(dsn, admin_dsn, host, port, data_dir, backend)`
  - `class LocalPostgres(data_dir, *, backend="pgserver", port=0, bin_dir=None, dbname="nova_agent", password=None)`，方法 `start() -> PgInfo`、`stop() -> None`（幂等）、`info` 属性。
  - 纯函数 `cleanup_stale(data_dir: Path) -> None`、`pgserver_info(uri, dbname, data_dir=None) -> PgInfo`、`pid_alive(pid) -> bool`、`free_port() -> int`、`ensure_database_sync(admin_dsn, dbname) -> None`。

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_local_pg.py`：

```python
import os
from pathlib import Path

import pytest

from app.local import pg as pg_module
from app.local.pg import (
    LocalPostgres,
    PgInfo,
    cleanup_stale,
    ensure_database_sync,
    free_port,
    pgserver_info,
    pid_alive,
)


def test_free_port_is_bindable():
    port = free_port()
    assert 0 < port < 65536


def test_pgserver_info_switches_database_name():
    info = pgserver_info(
        "postgresql://postgres@127.0.0.1:55432/postgres?connect_timeout=3",
        "nova_agent",
    )
    from psycopg.conninfo import conninfo_to_dict

    assert conninfo_to_dict(info.dsn)["dbname"] == "nova_agent"
    assert conninfo_to_dict(info.admin_dsn)["dbname"] == "postgres"
    assert info.host == "127.0.0.1"
    assert info.port == 55432


def test_cleanup_stale_removes_dead_pid(tmp_path, monkeypatch):
    pid_file = tmp_path / "postmaster.pid"
    pid_file.write_text("424242\nC:/nova/pgdata\n1700000000\n55432\n", encoding="utf-8")
    monkeypatch.setattr(pg_module, "pid_alive", lambda pid: False)
    cleanup_stale(tmp_path)
    assert not pid_file.exists()


def test_cleanup_stale_kills_orphan_postgres(tmp_path, monkeypatch):
    pid_file = tmp_path / "postmaster.pid"
    pid_file.write_text("424242\nC:/nova/pgdata\n1700000000\n55432\n", encoding="utf-8")
    killed: list[int] = []
    monkeypatch.setattr(pg_module, "pid_alive", lambda pid: True)
    monkeypatch.setattr(pg_module, "_pid_is_postgres", lambda pid: True)
    monkeypatch.setattr(pg_module, "_kill_tree_sync", lambda pid: killed.append(pid))
    cleanup_stale(tmp_path)
    assert killed == [424242]
    assert not pid_file.exists()


def test_cleanup_stale_does_not_kill_recycled_pid(tmp_path, monkeypatch):
    pid_file = tmp_path / "postmaster.pid"
    pid_file.write_text("424242\nC:/nova/pgdata\n1700000000\n55432\n", encoding="utf-8")
    killed: list[int] = []
    monkeypatch.setattr(pg_module, "pid_alive", lambda pid: True)
    monkeypatch.setattr(pg_module, "_pid_is_postgres", lambda pid: False)
    monkeypatch.setattr(pg_module, "_kill_tree_sync", lambda pid: killed.append(pid))
    cleanup_stale(tmp_path)
    assert killed == []
    assert not pid_file.exists()


def test_start_and_stop_are_idempotent(tmp_path, monkeypatch):
    info = PgInfo(
        dsn="postgresql://nova:pw@127.0.0.1:55432/nova_agent",
        admin_dsn="postgresql://nova:pw@127.0.0.1:55432/postgres",
        host="127.0.0.1",
        port=55432,
        data_dir=tmp_path,
        backend="pgserver",
    )
    local = LocalPostgres(tmp_path, backend="pgserver")
    monkeypatch.setattr(local, "_start_backend", lambda: info)
    monkeypatch.setattr(pg_module, "_wait_ready", lambda dsn, timeout=30: None)
    monkeypatch.setattr(pg_module, "ensure_database_sync", lambda dsn, db: None)
    stopped: list[bool] = []
    monkeypatch.setattr(local, "_stop_backend", lambda: stopped.append(True))

    assert local.start() == info
    assert local.start() == info
    local.stop()
    local.stop()
    assert stopped == [True]


def test_ensure_database_rejects_unsafe_name():
    with pytest.raises(ValueError, match="unsafe database name"):
        ensure_database_sync(
            "postgresql://nova:pw@127.0.0.1:55432/postgres",
            "nova; drop database postgres",
        )


@pytest.mark.skipif(
    os.getenv("NOVA_TEST_LOCAL_PG") != "1",
    reason="set NOVA_TEST_LOCAL_PG=1 to run the real PostgreSQL roundtrip "
    "(Task 0 decision: pgserver default, pg_ctl fallback)",
)
def test_local_pg_roundtrip(tmp_path):
    import psycopg

    backend = os.getenv("LOCAL_PG_BACKEND", "pgserver")
    bin_dir = os.getenv("LOCAL_PG_BIN_DIR") or None
    local = LocalPostgres(tmp_path / "pgdata", backend=backend, bin_dir=bin_dir)
    info = local.start()
    try:
        with psycopg.connect(info.dsn, connect_timeout=5) as conn:
            assert conn.execute("select 1").fetchone()[0] == 1
    finally:
        local.stop()
        local.stop()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && NOVA_TEST_FAST=1 python -m pytest tests/test_local_pg.py -q`

Expected: FAIL — `ImportError: cannot import name 'LocalPostgres'`；真实 PostgreSQL 测试应显示 skipped（理由包含 `NOVA_TEST_LOCAL_PG=1`）。

- [ ] **Step 3: 实现双后端生命周期**

创建 `backend/app/local/pg.py`：

```python
"""Embedded PostgreSQL lifecycle for local mode.

Backend A (pgserver) is a pip package with bundled binaries. Backend B
(pg_ctl) manages official PostgreSQL binaries and is the packaging fallback.
The launcher uses one of them; both expose the same PgInfo.
"""
import os
import secrets
import shutil
import signal
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import psycopg
import structlog
from psycopg.conninfo import conninfo_to_dict, make_conninfo

logger = structlog.get_logger()


@dataclass(frozen=True)
class PgInfo:
    dsn: str
    admin_dsn: str
    host: str
    port: int
    data_dir: Path
    backend: str


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
            return bool(ok) and code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _pid_is_postgres(pid: int) -> bool:
    if os.name == "nt":
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return "postgres.exe" in result.stdout.lower()
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "comm="],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return "postgres" in result.stdout.lower()


def _kill_tree_sync(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True, timeout=20,
        )
        return
    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def _read_pid(data_dir: Path) -> int | None:
    try:
        first = (data_dir / "postmaster.pid").read_text(encoding="utf-8").splitlines()[0]
        return int(first.strip())
    except (OSError, ValueError, IndexError):
        return None


def cleanup_stale(data_dir: Path) -> None:
    """Recover from a hard crash: stop an orphan PG, remove stale pid."""
    pid_file = data_dir / "postmaster.pid"
    if not pid_file.exists():
        return
    pid = _read_pid(data_dir)
    if pid and pid_alive(pid) and _pid_is_postgres(pid):
        logger.warning("local_pg_orphan_stop", pid=pid)
        _kill_tree_sync(pid)
        for _ in range(50):
            if not pid_alive(pid):
                break
            time.sleep(0.1)
    pid_file.unlink(missing_ok=True)


def ensure_database_sync(admin_dsn: str, dbname: str) -> None:
    if not dbname.replace("_", "").isalnum():
        raise ValueError(f"unsafe database name: {dbname!r}")
    with psycopg.connect(admin_dsn, autocommit=True, connect_timeout=5) as conn:
        exists = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (dbname,)
        ).fetchone()
        if not exists:
            conn.execute(f'CREATE DATABASE "{dbname}"')


def _wait_ready(dsn: str, timeout: int = 30) -> None:
    deadline = time.monotonic() + timeout
    last: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with psycopg.connect(dsn, connect_timeout=3) as conn:
                conn.execute("SELECT 1")
            return
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(0.25)
    raise RuntimeError(f"PostgreSQL did not become ready: {type(last).__name__}: {last}")


def pgserver_info(uri: str, dbname: str, data_dir: Path | None = None) -> PgInfo:
    params = conninfo_to_dict(uri)
    host = str(params.get("host") or "")
    if not host or host.startswith(("/", "\\", ".")) or "\\" in host:
        raise RuntimeError("pgserver 未提供 TCP 地址；Windows 请使用 LOCAL_PG_BACKEND=pg_ctl")
    port = int(params.get("port") or 5432)
    user = str(params.get("user") or "postgres")
    password = str(params.get("password") or "")
    common = {"host": host, "port": port, "user": user, "connect_timeout": 3}
    if password:
        common["password"] = password
    return PgInfo(
        dsn=make_conninfo(**common, dbname=dbname),
        admin_dsn=make_conninfo(**common, dbname="postgres"),
        host=host,
        port=port,
        data_dir=Path(data_dir) if data_dir is not None else Path("."),
        backend="pgserver",
    )


class LocalPostgres:
    def __init__(
        self,
        data_dir: Path,
        *,
        backend: str = "pgserver",
        port: int = 0,
        bin_dir: str | None = None,
        dbname: str = "nova_agent",
        password: str | None = None,
    ) -> None:
        if backend not in ("pgserver", "pg_ctl"):
            raise ValueError(f"unknown PostgreSQL backend: {backend}")
        self.data_dir = Path(data_dir)
        self.backend = backend
        self.port = port
        self.bin_dir = bin_dir
        self.dbname = dbname
        self.password = password
        self._server = None
        self._info: PgInfo | None = None
        self._started = False

    @property
    def info(self) -> PgInfo | None:
        return self._info

    def start(self) -> PgInfo:
        if self._started and self._info:
            return self._info
        self.data_dir.mkdir(parents=True, exist_ok=True)
        cleanup_stale(self.data_dir)
        try:
            info = self._start_backend()
            self._started = True
            _wait_ready(info.admin_dsn, timeout=30)
            ensure_database_sync(info.admin_dsn, self.dbname)
            _wait_ready(info.dsn, timeout=10)
        except Exception:
            # Never leave a half-started postgres behind when init/migration fails.
            try:
                self._stop_backend()
            except Exception:
                logger.exception("local_pg_start_cleanup_failed", backend=self.backend)
            self._server = None
            self._started = False
            raise
        self._info = info
        logger.info(
            "local_pg_started", backend=self.backend, host=info.host,
            port=info.port, data_dir=str(self.data_dir),
        )
        return info

    def stop(self) -> None:
        if not self._started:
            return
        try:
            self._stop_backend()
        except Exception:
            logger.exception("local_pg_stop_failed", backend=self.backend)
            pid = _read_pid(self.data_dir)
            if pid and pid_alive(pid):
                _kill_tree_sync(pid)
        finally:
            self._started = False
            self._server = None
            logger.info("local_pg_stopped", backend=self.backend)

    def _start_backend(self) -> PgInfo:
        if self.backend == "pgserver":
            return self._start_pgserver()
        return self._start_pgctl()

    def _stop_backend(self) -> None:
        if self.backend == "pgserver":
            if self._server is not None:
                self._server.cleanup()
            return
        self._stop_pgctl()

    def _start_pgserver(self) -> PgInfo:
        try:
            import pgserver
        except ImportError as exc:
            raise RuntimeError(
                "pgserver 未安装：请安装 backend/requirements-local.txt，"
                "或设置 LOCAL_PG_BACKEND=pg_ctl"
            ) from exc
        self._server = pgserver.get_server(str(self.data_dir))
        return pgserver_info(self._server.get_uri(), self.dbname, self.data_dir)

    def _pg_bins(self) -> tuple[Path, Path]:
        if self.bin_dir:
            base = Path(self.bin_dir)
            initdb = base / ("initdb.exe" if os.name == "nt" else "initdb")
        else:
            found = shutil.which("initdb")
            if not found:
                raise RuntimeError(
                    "找不到 initdb：请设置 LOCAL_PG_BIN_DIR 指向 PostgreSQL bin 目录"
                )
            initdb = Path(found)
        pg_ctl = initdb.with_name("pg_ctl.exe" if os.name == "nt" else "pg_ctl")
        if not initdb.exists() or not pg_ctl.exists():
            raise RuntimeError(f"PostgreSQL binaries missing under {initdb.parent}")
        return initdb, pg_ctl

    def _password_file(self) -> tuple[Path, str]:
        path = self.data_dir / "pgpassword"
        if path.exists():
            return path, path.read_text(encoding="utf-8").strip()
        password = self.password or secrets.token_urlsafe(24)
        path.write_text(password, encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return path, password

    def _start_pgctl(self) -> PgInfo:
        initdb, pg_ctl = self._pg_bins()
        password_path, password = self._password_file()
        if not (self.data_dir / "PG_VERSION").exists():
            subprocess.run(
                [
                    str(initdb), "-D", str(self.data_dir), "-U", "nova",
                    "--auth=scram-sha-256", f"--pwfile={password_path}",
                    "-E", "UTF8",
                ],
                check=True, capture_output=True, timeout=180,
            )
        port = self.port or free_port()
        logfile = self.data_dir / "postgres.log"
        subprocess.run(
            [
                str(pg_ctl), "-D", str(self.data_dir), "-l", str(logfile),
                "-o", f"-p {port} -h 127.0.0.1", "-w", "-t", "60", "start",
            ],
            check=True, capture_output=True, timeout=90,
        )
        user = quote(password, safe="")
        dsn = f"postgresql://nova:{user}@127.0.0.1:{port}/{self.dbname}?connect_timeout=3"
        admin = f"postgresql://nova:{user}@127.0.0.1:{port}/postgres?connect_timeout=3"
        return PgInfo(
            dsn=dsn, admin_dsn=admin, host="127.0.0.1", port=port,
            data_dir=self.data_dir, backend="pg_ctl",
        )

    def _stop_pgctl(self) -> None:
        _, pg_ctl = self._pg_bins()
        try:
            subprocess.run(
                [
                    str(pg_ctl), "-D", str(self.data_dir),
                    "-m", "fast", "-w", "-t", "30", "stop",
                ],
                check=True, capture_output=True, timeout=45,
            )
        finally:
            pid = _read_pid(self.data_dir)
            if pid and pid_alive(pid):
                _kill_tree_sync(pid)
```

若 Task 0 判定 A，创建 `backend/requirements-local.txt`：

```text
# Local runtime only. Never installed by the cloud image.
pgserver==0.1.4
```

若判定 B，创建同名文件但内容为注释，明确依赖系统/打包的 PostgreSQL 16 二进制：

```text
# Local runtime uses PostgreSQL 16 binaries managed by pg_ctl.
# Set LOCAL_PG_BIN_DIR to the directory containing initdb/pg_ctl.
# No pip dependency is required for the database itself.
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && NOVA_TEST_FAST=1 python -m pytest tests/test_local_pg.py -q`

Expected: PASS；真实 roundtrip 测试 skipped，理由为 `set NOVA_TEST_LOCAL_PG=1 to run the real PostgreSQL roundtrip (Task 0 decision: pgserver default, pg_ctl fallback)`。

- [ ] **Step 5: 全量回归与提交**

Run: `cd backend && NOVA_TEST_FAST=1 python -m pytest tests -q && ruff check app tests`

Expected: 全绿，ruff `All checks passed!`。

```bash
git add backend/app/local/pg.py backend/tests/test_local_pg.py
git add backend/requirements-local.txt 2>/dev/null || true
git commit -m "feat: add embedded PostgreSQL lifecycle for local mode"
```

---

## Task 4: 本地启动器、设置校验与 `nova.py local`

**Files:**
- Create: `backend/app/local/runtime.py`
- Create: `backend/app/local/launcher.py`
- Modify: `backend/app/main.py`
- Modify: `backend/nova.py`
- Test: `backend/tests/test_local_launcher.py`

**Interfaces:**
- Consumes: Task 2 的 `load_or_create` / `runtime_env`；Task 3 的 `LocalPostgres` / `PgInfo`。
- Produces:
  - `validate_local_settings() -> None`
  - `run(config, *, host="127.0.0.1", port=0, environ=None, pg_factory=None, app_factory=None, server_factory=None) -> int`
  - `free_port()` 使用 Task 3 的 `free_port`；`nova.py local --config --host --port --pg-backend`。

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_local_launcher.py`：

```python
import types
from pathlib import Path

import pytest

from app.config import settings
from app.local import launcher
from app.local.pg import PgInfo


def _info(tmp_path: Path) -> PgInfo:
    return PgInfo(
        dsn="postgresql://nova:pw@127.0.0.1:55432/nova_agent",
        admin_dsn="postgresql://nova:pw@127.0.0.1:55432/postgres",
        host="127.0.0.1", port=55432, data_dir=tmp_path, backend="pgserver",
    )


def test_validate_local_settings_rejects_default_secret(tmp_path, monkeypatch):
    from app.local.runtime import validate_local_settings

    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(settings, "nova_data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "secret_key", "change-me-in-production")
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        validate_local_settings()


def test_validate_local_settings_creates_data_dirs(tmp_path, monkeypatch):
    from app.local.runtime import validate_local_settings

    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(settings, "nova_data_dir", str(tmp_path / "Nova"))
    monkeypatch.setattr(settings, "local_tmp_dir", "")
    monkeypatch.setattr(settings, "log_dir", str(tmp_path / "Nova" / "logs"))
    monkeypatch.setattr(settings, "secret_key", "x" * 64)
    validate_local_settings()
    assert (tmp_path / "Nova").is_dir()
    assert (tmp_path / "Nova" / "tmp").is_dir()
    assert (tmp_path / "Nova" / "logs").is_dir()


def test_validate_local_settings_is_noop_in_server_mode(tmp_path, monkeypatch):
    from app.local.runtime import validate_local_settings

    monkeypatch.setattr(settings, "nova_mode", "server")
    monkeypatch.setattr(settings, "secret_key", "change-me-in-production")
    validate_local_settings()


def test_run_injects_dsn_and_stops_pg_in_order(tmp_path):
    events: list[str] = []
    environ: dict[str, str] = {}

    class FakePg:
        def __init__(self, data_dir, **kwargs):
            events.append("pg_init")

        def start(self):
            events.append("pg_start")
            return _info(tmp_path)

        def stop(self):
            events.append("pg_stop")

    class FakeServer:
        def __init__(self, app, host, port):
            events.append(f"server_init:{host}:{port}")

        def run(self):
            assert environ["POSTGRES_DSN_OVERRIDE"].startswith("postgresql://")
            events.append("server_run")

    config = {
        "version": 1, "mode": "local", "dataDir": str(tmp_path),
        "secretKey": "s" * 64, "pgBackend": "pgserver", "allowInstallDeps": False,
    }
    code = launcher.run(
        config, port=0, environ=environ,
        pg_factory=FakePg,
        app_factory=lambda: object(),
        server_factory=FakeServer,
    )
    assert code == 0
    assert events[0] == "pg_init"
    assert events[1] == "pg_start"
    assert events[-2] == "server_run"
    assert events[-1] == "pg_stop"
    assert environ["NOVA_MODE"] == "local"
    assert environ["SECRET_KEY"] == "s" * 64


def test_run_rejects_non_loopback_host(tmp_path):
    config = {"dataDir": str(tmp_path), "secretKey": "s" * 64}
    with pytest.raises(ValueError, match="loopback"):
        launcher.run(config, host="0.0.0.0", environ={}, pg_factory=object)


def test_cmd_local_forwards_flags(monkeypatch, tmp_path):
    import nova

    calls: dict = {}
    cfg = {"dataDir": str(tmp_path), "secretKey": "s" * 64, "pgBackend": "pgserver"}
    monkeypatch.setattr("app.local.config.load_or_create", lambda path: cfg)
    monkeypatch.setattr(
        "app.local.launcher.run",
        lambda config, **kwargs: calls.update(config=config, **kwargs) or 0,
    )
    args = types.SimpleNamespace(
        config=None, pg_backend="pg_ctl", host="127.0.0.1", port=0,
    )
    assert nova.cmd_local(args) == 0
    assert calls["config"]["pgBackend"] == "pg_ctl"
    assert calls["host"] == "127.0.0.1"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && NOVA_TEST_FAST=1 python -m pytest tests/test_local_launcher.py -q`

Expected: FAIL — `ModuleNotFoundError: app.local.runtime` / `launcher`。

- [ ] **Step 3: 实现校验与启动器**

创建 `backend/app/local/runtime.py`：

```python
"""Local-mode setting validation. Called from the FastAPI lifespan."""
from pathlib import Path

from app.config import settings

DEFAULT_SECRET = "change-me-in-production"


def validate_local_settings() -> None:
    if not settings.is_local:
        return
    if len(settings.secret_key) < 32 or settings.secret_key == DEFAULT_SECRET:
        raise RuntimeError(
            "local mode requires a generated SECRET_KEY "
            "(start with `python nova.py local`, not bare uvicorn)"
        )
    root = settings.data_root
    root.mkdir(parents=True, exist_ok=True)
    settings.local_tmp_root.mkdir(parents=True, exist_ok=True)
    Path(settings.log_dir).mkdir(parents=True, exist_ok=True)
```

创建 `backend/app/local/launcher.py`：

```python
"""Start PostgreSQL before importing the Settings singleton, then uvicorn."""
import json
import os
from pathlib import Path

from app.local.config import runtime_env
from app.local.pg import LocalPostgres, free_port

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _load_app():
    from app.main import app

    return app


def _uvicorn_server(app, host: str, port: int):
    import uvicorn

    return uvicorn.Server(
        uvicorn.Config(app, host=host, port=port, log_level="info", access_log=False)
    )


def run(
    config: dict,
    *,
    host: str = "127.0.0.1",
    port: int = 0,
    environ=None,
    pg_factory=None,
    app_factory=None,
    server_factory=None,
) -> int:
    if host not in LOOPBACK_HOSTS:
        raise ValueError("local mode must bind a loopback host (127.0.0.1)")
    env_map = os.environ if environ is None else environ
    env = runtime_env(config)
    env_map.update(env)

    factory = pg_factory or LocalPostgres
    pg = factory(
        Path(env["LOCAL_PG_DATA_DIR"]),
        backend=env["LOCAL_PG_BACKEND"],
        port=int(config.get("pgPort") or 0),
        bin_dir=env["LOCAL_PG_BIN_DIR"] or None,
    )
    info = pg.start()
    env_map["POSTGRES_DSN_OVERRIDE"] = info.dsn
    listen_port = port or free_port()
    try:
        app = (app_factory or _load_app)()
        server = (server_factory or _uvicorn_server)(app, host, listen_port)
        print(
            json.dumps(
                {"event": "listening", "url": f"http://{host}:{listen_port}"},
                ensure_ascii=False,
            ),
            flush=True,
        )
        server.run()
    finally:
        pg.stop()
    return 0
```

修改 `backend/app/main.py` 的 lifespan，在 `setup_logging()` 之后加入：

```python
    if settings.is_local:
        from app.local.runtime import validate_local_settings

        validate_local_settings()
```

修改 `backend/app/main.py` 的静态前端挂载条件：

```python
if (settings.app_env == "prod" or settings.is_local) and _FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=_FRONTEND_DIST, html=True), name="frontend")
```

修改 `backend/nova.py`：在 `cmd_agent` 之后新增：

```python
def cmd_local(args) -> int:
    from app.local.config import load_or_create
    from app.local.launcher import run

    config = load_or_create(args.config)
    if args.pg_backend:
        config["pgBackend"] = args.pg_backend
    return run(config, host=args.host, port=args.port)
```

在 `main()` 的子命令注册区、`p_agent` 之后加入：

```python
    p_local = sub.add_parser("local", help="以本地模式启动后端（内嵌 PostgreSQL）")
    p_local.add_argument("--config", help="nova-config.json 路径（默认 %%APPDATA%%/Nova/nova-config.json）")
    p_local.add_argument("--host", default="127.0.0.1")
    p_local.add_argument("--port", type=int, default=0, help="0 = 随机空闲端口")
    p_local.add_argument("--pg-backend", choices=["pgserver", "pg_ctl"])
    p_local.set_defaults(func=cmd_local)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && NOVA_TEST_FAST=1 python -m pytest tests/test_local_launcher.py -q`

Expected: PASS，6 passed。

- [ ] **Step 5: 验证 `nova.py local --help`**

Run: `cd backend && python nova.py local --help`

Expected: 输出包含 `--config`、`--host`、`--port`、`--pg-backend`，退出码 0。

- [ ] **Step 6: 全量回归与提交**

Run: `cd backend && NOVA_TEST_FAST=1 python -m pytest tests -q && ruff check app tests`

Expected: 全绿；ruff `All checks passed!`。

```bash
git add backend/app/local/runtime.py backend/app/local/launcher.py backend/app/main.py backend/nova.py backend/tests/test_local_launcher.py
git commit -m "feat: add local launcher with embedded PostgreSQL startup"
```

---

## Task 5: 固定本地用户与本地认证绕过

**Files:**
- Modify: `backend/app/core/security/auth.py`
- Modify: `backend/app/core/security/limits.py`
- Modify: `backend/app/api/v1/auth.py`
- Modify: `backend/app/db/init_db.py`（`init_all` 的本地/云端分支）
- Test: `backend/tests/test_local_auth.py`

**Interfaces:**
- Consumes: `settings.is_local`、`settings.local_user`。
- Produces:
  - `ensure_local_user() -> dict`：幂等 seed，角色固定 `local`。
  - `get_local_user() -> dict`：无 Cookie 的请求身份；不存在时 503。
  - `get_current_user` 在本地模式第一行直接返回 `get_local_user()`。
  - `require_admin` 在本地模式直接返回当前用户。
  - 账号路由本地返回 404；`/auth/me` 与 `/auth/config` 保留。

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_local_auth.py`：

```python
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.config import settings
from app.core.security import auth
from app.core.security.limits import check_chat_quota, ensure_token_budget


def _user_row() -> tuple:
    base = (1, "local", "本地用户", "local", "active", False, None, 0, None)
    return base + (None,) * 8


@pytest.mark.asyncio
async def test_ensure_local_user_upserts_fixed_username(monkeypatch):
    calls: list[tuple] = []

    async def fake_execute(sql, params):
        calls.append((sql, params))
        return []

    async def fake_get_local_user():
        return {"id": 1, "username": settings.local_user, "role": "local"}

    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(auth, "execute", fake_execute)
    monkeypatch.setattr(auth, "get_local_user", fake_get_local_user)
    user = await auth.ensure_local_user()
    assert user["username"] == settings.local_user
    assert "INSERT INTO users" in calls[0][0]
    assert calls[0][1][0] == settings.local_user


@pytest.mark.asyncio
async def test_get_local_user_reads_quota_columns(monkeypatch):
    async def fake_query(sql, params):
        return [_user_row()]

    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(auth, "query", fake_query)
    user = await auth.get_local_user()
    assert user["username"] == "local"
    assert user["quota_daily_tokens"] is None
    assert user["role"] == "local"


@pytest.mark.asyncio
async def test_get_current_user_local_bypasses_cookie(monkeypatch):
    async def fake_get_local_user():
        return {"id": 1, "username": "local", "role": "local"}

    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(auth, "get_local_user", fake_get_local_user)
    request = Request({"type": "http", "headers": []})
    user = await auth.get_current_user(request)
    assert user["username"] == "local"


@pytest.mark.asyncio
async def test_require_admin_local_returns_local_user(monkeypatch):
    monkeypatch.setattr(settings, "nova_mode", "local")
    user = {"id": 1, "username": "local", "role": "local"}
    assert await auth.require_admin(user) == user


def test_account_routes_are_server_only(monkeypatch):
    from app.api.v1 import auth as auth_api

    monkeypatch.setattr(settings, "nova_mode", "local")
    with pytest.raises(HTTPException) as exc:
        auth_api._ensure_server_mode()
    assert exc.value.status_code == 404


def test_auth_config_local_disables_registration(monkeypatch):
    from app.api.v1 import auth as auth_api

    monkeypatch.setattr(settings, "nova_mode", "local")
    cfg = auth_api.auth_config()
    assert cfg.registration_mode == "closed"
    assert cfg.guest_enabled is False


@pytest.mark.asyncio
async def test_local_mode_skips_quota_checks(monkeypatch):
    async def boom(*args, **kwargs):
        raise AssertionError("quota DB must not be touched in local mode")

    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr("app.core.security.limits.messages_last_hour", boom)
    monkeypatch.setattr("app.core.security.limits.tokens_used_today", boom)
    await check_chat_quota({"id": 1, "is_guest": False})
    await ensure_token_budget({"id": 1, "role": "local"})
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && NOVA_TEST_FAST=1 python -m pytest tests/test_local_auth.py -q`

Expected: FAIL — `AttributeError: module 'app.core.security.auth' has no attribute 'ensure_local_user'`。

- [ ] **Step 3: 实现本地身份**

在 `backend/app/core/security/auth.py` 顶部加入 `import secrets`，在 `ensure_default_users` 之前加入：

```python
async def get_local_user() -> dict:
    rows = await query(
        "SELECT id, username, display_name, role, status, is_guest, expires_at, "
        f"token_version, created_at{QUOTA_SELECT} FROM users WHERE username = %s",
        (settings.local_user,),
    )
    if not rows:
        raise HTTPException(status_code=503, detail="本地用户尚未初始化，请重启应用")
    r = rows[0]
    user = _with_quota({
        "id": r[0], "username": r[1], "display_name": r[2] or r[1],
        "role": r[3], "status": r[4] or "active", "is_guest": bool(r[5]),
        "expires_at": r[6], "token_version": int(r[7] or 0),
        "created_at": r[8],
    }, r, 9)
    if not _active(user):
        raise HTTPException(status_code=403, detail="本地用户不可用")
    return user


async def ensure_local_user() -> dict:
    """Idempotently seed the single local user. No password is ever used."""
    await execute(
        """
        INSERT INTO users (username, password_hash, display_name, role)
        VALUES (%s, %s, %s, 'local')
        ON CONFLICT (username) DO UPDATE SET role = 'local', status = 'active'
        """,
        (settings.local_user, hash_password(secrets.token_urlsafe(32)), "本地用户"),
    )
    return await get_local_user()
```

把 `get_current_user` 的开头改为：

```python
async def get_current_user(request: Request) -> dict:
    if settings.is_local:
        return await get_local_user()
    token = request.cookies.get(COOKIE_NAME)
```

把 `require_admin` 改为：

```python
async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if settings.is_local:
        return user
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user
```

在 `backend/app/core/security/limits.py` 的每个检查函数第一行加入本地短路：

```python
    if settings.is_local:
        return
```

受影响的函数：`check_chat_quota`、`check_sandbox_quota`、`check_job_quota`、`check_search_quota`、`ensure_token_budget`。`ensure_token_budget` 的短路必须放在 `user is None` 分支之前：

```python
async def ensure_token_budget(
    user: dict | None = None,
    *,
    user_id: int | None = None,
    extra_tokens: int = 0,
) -> None:
    if settings.is_local:
        return
    # 其余实现保持原样，不得移动或改写
```

在 `backend/app/api/v1/auth.py` 中加入：

```python
def _ensure_server_mode() -> None:
    if settings.is_local:
        raise HTTPException(status_code=404, detail="本地模式不提供账号登录/注册")
```

在以下路由函数体内第一行调用 `_ensure_server_mode()`：
`email_code`、`login`、`register`、`guest`、`logout`、`update_my_profile`、`update_my_password`、`reset_password`、`reset_password_by_email`。

`auth_config` 改为：

```python
@router.get("/auth/config", response_model=AuthConfigOut)
async def auth_config():
    if settings.is_local:
        return AuthConfigOut(
            registration_mode="closed",
            guest_enabled=False,
            invite_required=False,
            min_password_length=settings.min_password_length,
            email_verification=False,
        )
    return AuthConfigOut(
        registration_mode=settings.registration_mode,
        guest_enabled=settings.guest_enabled,
        invite_required=settings.registration_mode == "invite",
        min_password_length=settings.min_password_length,
        email_verification=settings.email_enabled and settings.email_verify_required,
    )
```

在 `backend/app/db/init_db.py` 的 `init_all()` 中，把 storage/Qdrant/users 三段改为模式分支：

```python
    if settings.is_local:
        result["storage"] = "skipped: local mode"
    else:
        try:
            from app.core.storage.user_storage import migrate_legacy_repos
            result["storage"] = await migrate_legacy_repos()
        except Exception as exc:  # noqa: BLE001
            result["storage"] = f"failed: {exc}"
            logger.error("repo_storage_migration_failed", error=str(exc))

    if not settings.use_embeddings:
        result["qdrant"] = "skipped: embeddings disabled"
        result["qdrant_payload"] = "skipped: embeddings disabled"
    else:
        try:
            result["qdrant"] = await init_qdrant()
        except Exception as exc:  # noqa: BLE001
            result["qdrant"] = f"failed: {exc}"
            logger.error("qdrant_init_failed", error=str(exc))

        try:
            from app.db.qdrant import backfill_repo_user_payload
            repos = await query("SELECT id, user_id FROM repos")
            for repo_id, user_id in repos:
                await backfill_repo_user_payload(str(repo_id), int(user_id))
            result["qdrant_payload"] = len(repos)
        except Exception as exc:  # noqa: BLE001
            result["qdrant_payload"] = f"failed: {exc}"
            logger.warning("qdrant_payload_backfill_failed", error=str(exc))

    if settings.is_local:
        try:
            from app.core.security.auth import ensure_local_user
            user = await ensure_local_user()
            result["users"] = f"local: {user['username']}"
        except Exception as exc:  # noqa: BLE001
            result["users"] = f"failed: {exc}"
            logger.error("local_user_seed_failed", error=str(exc))
    else:
        try:
            from app.core.security.auth import ensure_default_users
            result["users"] = await ensure_default_users()
        except Exception as exc:  # noqa: BLE001
            result["users"] = f"failed: {exc}"
            logger.error("user_seed_failed", error=str(exc))
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && NOVA_TEST_FAST=1 python -m pytest tests/test_local_auth.py tests/test_auth.py -q`

Expected: PASS；现有 auth 测试不回归。

- [ ] **Step 5: 全量回归与提交**

Run: `cd backend && NOVA_TEST_FAST=1 python -m pytest tests -q && ruff check app tests`

Expected: 全绿。

```bash
git add backend/app/core/security/auth.py backend/app/core/security/limits.py backend/app/api/v1/auth.py backend/app/db/init_db.py backend/tests/test_local_auth.py
git commit -m "feat: add fixed local user and local-only auth bypass"
```

---

## Task 6: 本地文件夹项目、`repos.origin` 与 gitignore 索引

**Files:**
- Create: `backend/app/local/projects.py`
- Modify: `backend/app/core/indexing/pipeline.py`
- Modify: `backend/app/core/indexing/walker.py`
- Modify: `backend/app/db/init_db.py`（migration 18）
- Modify: `backend/app/models/schemas.py`
- Modify: `backend/app/api/v1/repos.py`
- Modify: `frontend/src/lib/types.ts`（`Repo.origin`）
- Test: `backend/tests/test_local_projects.py`

**Interfaces:**
- Consumes: Task 5 的本地用户；`settings.data_root`；`create_repo_row`。
- Produces:
  - `validate_local_project_path(raw: str, data_root: Path) -> Path`
  - `register_local_project(user: dict, raw_path: str, name: str | None = None) -> dict`
  - `create_local_repo_row(user_id: int, name: str, root_path: str, repo_id: str) -> dict`
  - `iter_local_project_files(root: str, max_file_bytes: int)` yields `(rel, abspath, size)`。
  - `POST /api/v1/repos/local`，body `{"path": "...", "name": "..."}`。
  - `repos.origin`：`upload | git | local`；本地项目删除只注销，不删除用户目录。

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_local_projects.py`：

```python
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from app.config import settings
from app.core.indexing import pipeline
from app.core.indexing.walker import iter_local_project_files
from app.local.projects import register_local_project, validate_local_project_path


def test_validate_local_project_accepts_directory_with_spaces(tmp_path):
    project = tmp_path / "My Project"
    project.mkdir()
    assert validate_local_project_path(str(project), tmp_path / "NovaData") == project.resolve()


def test_validate_local_project_rejects_relative_path(tmp_path):
    with pytest.raises(ValueError, match="绝对路径"):
        validate_local_project_path("relative/project", tmp_path / "NovaData")


def test_validate_local_project_rejects_unc(tmp_path):
    with pytest.raises(ValueError, match="UNC"):
        validate_local_project_path(r"\\server\share\repo", tmp_path / "NovaData")


def test_validate_local_project_rejects_data_dir(tmp_path):
    data = tmp_path / "NovaData"
    project = data / "project"
    project.mkdir(parents=True)
    with pytest.raises(ValueError, match="数据目录"):
        validate_local_project_path(str(project), data)


def test_validate_local_project_rejects_missing_and_file(tmp_path):
    with pytest.raises(ValueError, match="不存在"):
        validate_local_project_path(str(tmp_path / "missing"), tmp_path / "NovaData")
    file_path = tmp_path / "a.py"
    file_path.write_text("print(1)", encoding="utf-8")
    with pytest.raises(ValueError, match="目录"):
        validate_local_project_path(str(file_path), tmp_path / "NovaData")


def test_validate_local_project_rejects_filesystem_root(tmp_path):
    with pytest.raises(ValueError, match="根目录"):
        validate_local_project_path(str(Path(tmp_path.anchor)), tmp_path / "NovaData")


@pytest.mark.asyncio
async def test_register_local_project_creates_and_indexes(monkeypatch, tmp_path):
    project = tmp_path / "repo"
    project.mkdir()
    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(settings, "nova_data_dir", str(tmp_path / "NovaData"))

    async def no_existing(sql, params):
        return []

    async def fake_create(user_id, name, root_path, repo_id):
        return {"id": repo_id, "name": name, "origin": "local", "root_path": root_path}

    enqueued: list[tuple] = []

    async def fake_enqueue(repo_id, **kwargs):
        enqueued.append((repo_id, kwargs))
        return "job-1"

    async def fake_audit(*args, **kwargs):
        return None

    monkeypatch.setattr("app.local.projects.query", no_existing)
    monkeypatch.setattr("app.local.projects.create_local_repo_row", fake_create)
    monkeypatch.setattr("app.local.projects.enqueue_index", fake_enqueue)
    monkeypatch.setattr("app.local.projects.log_audit", fake_audit)
    repo = await register_local_project({"id": 1}, str(project))
    assert repo["origin"] == "local"
    assert enqueued and enqueued[0][1]["user_id"] == 1


@pytest.mark.asyncio
async def test_delete_local_repo_never_removes_project_files(monkeypatch, tmp_path):
    project = tmp_path / "repo"
    project.mkdir()
    removed: list[Path] = []
    monkeypatch.setattr(settings, "nova_mode", "local")

    async def fake_get(repo_id, user_id):
        return {"id": repo_id, "user_id": user_id, "origin": "local", "root_path": str(project)}

    async def fake_execute(sql, params):
        return []

    monkeypatch.setattr(pipeline, "get_repo", fake_get)
    monkeypatch.setattr(pipeline, "execute", fake_execute)
    monkeypatch.setattr(pipeline.shutil, "rmtree", lambda path, **kwargs: removed.append(Path(path)))
    monkeypatch.setattr(
        "app.core.deploy.service.cleanup_repo_resources",
        lambda *args, **kwargs: _async_none(),
    )
    assert await pipeline.delete_repo("00000000-0000-0000-0000-000000000001", 1) is True
    assert removed == []
    assert project.is_dir()


async def _async_none():
    return None


def _git_available() -> bool:
    return shutil.which("git") is not None


@pytest.mark.skipif(not _git_available(), reason="git executable not available")
def test_iter_local_project_files_respects_gitignore(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".gitignore").write_text("ignored.py\n", encoding="utf-8")
    (tmp_path / "keep.py").write_text("print('keep')", encoding="utf-8")
    (tmp_path / "ignored.py").write_text("print('ignored')", encoding="utf-8")
    paths = [rel for rel, _abspath, _size in iter_local_project_files(str(tmp_path), 100_000)]
    assert "keep.py" in paths
    assert "ignored.py" not in paths


def test_iter_local_project_files_falls_back_to_walk(tmp_path, monkeypatch):
    (tmp_path / "a.py").write_text("print('a')", encoding="utf-8")
    monkeypatch.setattr("app.core.indexing.walker._git_listed_files", lambda root: None)
    paths = [rel for rel, _abspath, _size in iter_local_project_files(str(tmp_path), 100_000)]
    assert paths == ["a.py"]


def test_iter_local_project_files_skips_symlink_escape(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("print('outside')", encoding="utf-8")
    link = root / "link.py"
    try:
        os.symlink(outside, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation not permitted on this platform")
    monkeypatch.setattr(
        "app.core.indexing.walker._git_listed_files", lambda root: ["link.py"]
    )
    paths = [rel for rel, _abspath, _size in iter_local_project_files(str(root), 100_000)]
    assert paths == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && NOVA_TEST_FAST=1 python -m pytest tests/test_local_projects.py -q`

Expected: FAIL — `ModuleNotFoundError: app.local.projects`；`iter_local_project_files` 不存在。

- [ ] **Step 3: 实现路径校验与登记**

创建 `backend/app/local/projects.py`：

```python
"""Register an existing user folder as a project without copying it."""
import os
import uuid
from pathlib import Path

import structlog

from app.config import settings
from app.core.indexing.pipeline import create_local_repo_row, get_repo
from app.core.jobs.service import enqueue_index
from app.core.security.audit import AuditAction, log_audit
from app.db import query

logger = structlog.get_logger()


def validate_local_project_path(raw: str, data_root: Path) -> Path:
    text = (raw or "").strip()
    if not text or "\x00" in text:
        raise ValueError("项目路径不能为空")
    if text.startswith(("\\\\", "//")):
        raise ValueError("不支持 UNC/设备路径，请选择本机磁盘目录")
    if os.name == "nt" and text.startswith(("\\", "/")):
        raise ValueError("请输入绝对路径，例如 D:\\code\\my-project")
    path = Path(text).expanduser()
    if not path.is_absolute():
        raise ValueError("请输入项目目录的绝对路径")
    try:
        root = path.resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"目录不存在或无法访问：{text}") from exc
    if not root.is_dir():
        raise ValueError(f"不是目录：{text}")
    if root.parent == root:
        raise ValueError("不能直接打开磁盘根目录")
    data = data_root.expanduser().resolve()
    if root == data or data in root.parents:
        raise ValueError("不能打开 Nova 数据目录或其子目录")
    if not os.access(root, os.R_OK):
        raise ValueError("目录不可读，请检查 Windows 权限")
    return root


async def register_local_project(
    user: dict, raw_path: str, name: str | None = None
) -> dict:
    if not settings.is_local:
        raise ValueError("本地模式未启用")
    root = validate_local_project_path(raw_path, settings.data_root)
    rows = await query(
        "SELECT id FROM repos WHERE user_id = %s AND lower(root_path) = lower(%s) LIMIT 1",
        (user["id"], str(root)),
    )
    if rows:
        existing = await get_repo(str(rows[0][0]), user["id"])
        if existing:
            return existing
    repo_id = str(uuid.uuid4())
    display = (name or root.name).strip()[:200] or root.name
    repo = await create_local_repo_row(user["id"], display, str(root), repo_id)
    await enqueue_index(repo_id, user_id=user["id"])
    await log_audit(
        AuditAction.REPO_IMPORT,
        user_id=str(user["id"]),
        details={"repo_id": repo_id, "source": "local"},
    )
    logger.info("local_project_registered", repo_id=repo_id)
    return repo
```

- [ ] **Step 4: 实现 `origin`、索引与删除保护**

在 `backend/app/db/init_db.py` 的 `_MIGRATIONS` 末尾（migration 17 之后）加入：

```python
    (18, [
        "ALTER TABLE repos ADD COLUMN IF NOT EXISTS origin VARCHAR(12) NOT NULL DEFAULT 'upload'",
        "UPDATE repos SET origin = 'git' WHERE source LIKE 'git:%' AND origin = 'upload'",
    ]),
```

在 `backend/app/models/schemas.py` 的 `RepoOut` 中加入：

```python
    origin: str = "upload"        # upload | git | local
```

并在 `RepoImportGit` 之前加入：

```python
class RepoLocalCreate(BaseModel):
    path: str = Field(min_length=1, max_length=2000)
    name: Optional[str] = Field(default=None, max_length=120)
```

修改 `backend/app/core/indexing/pipeline.py`：

```python
async def create_repo_row(
    user_id: int, name: str, source: str, repo_id: str, origin: str = "upload"
) -> dict:
    from app.core.storage.user_storage import repo_container
    root = repo_container(user_id, repo_id)
    root.mkdir(parents=True, exist_ok=True)
    root_path = str(root)
    await execute(
        "INSERT INTO repos (id, user_id, name, source, root_path, status, origin) "
        "VALUES (%s, %s, %s, %s, %s, 'pending', %s)",
        (repo_id, user_id, name[:200], source[:500], root_path, origin),
    )
    return {"id": repo_id, "name": name[:200], "source": source[:500],
            "root_path": root_path, "status": "pending", "origin": origin}


async def create_local_repo_row(
    user_id: int, name: str, root_path: str, repo_id: str
) -> dict:
    source = f"local:{root_path}"
    await execute(
        "INSERT INTO repos (id, user_id, name, source, root_path, status, origin) "
        "VALUES (%s, %s, %s, %s, %s, 'pending', 'local')",
        (repo_id, user_id, name[:200], source[:500], root_path),
    )
    return {"id": repo_id, "name": name[:200], "source": source[:500],
            "root_path": root_path, "status": "pending", "origin": "local"}
```

修改 `get_repo` 的 SELECT 与返回：

```python
    sql = ("SELECT id, user_id, name, source, root_path, status, error, stats, created_at, kind, rules, "
           "stack_mode, brief, smoke, origin FROM repos WHERE id = %s")
```

```python
        "stack_mode": r[11] or "python", "brief": r[12] or "", "smoke": r[13],
        "origin": r[14] or "upload",
```

修改 `list_repos`：

```python
    rows = await query(
        "SELECT id, name, source, status, error, stats, created_at, kind, origin FROM repos "
        "WHERE user_id = %s ORDER BY created_at DESC",
        (user_id,),
    )
    return [
        {"id": str(r[0]), "name": r[1], "source": r[2], "status": r[3],
         "error": r[4], "stats": r[5] or {}, "created_at": r[6], "kind": r[7] or "import",
         "origin": r[8] or "upload"}
        for r in rows
    ]
```

修改 `delete_repo` 的文件删除段：

```python
    await execute("DELETE FROM repos WHERE id = %s AND user_id = %s", (repo_id, user_id))
    if repo.get("origin") == "local":
        logger.info("local_project_unregistered", repo_id=repo_id)
    else:
        from app.core.storage.user_storage import repo_container
        shutil.rmtree(repo_container(user_id, repo_id), ignore_errors=True)
        shutil.rmtree(Path(settings.repos_dir) / repo_id, ignore_errors=True)
```

修改 `index_repo` 的根目录处理与文件枚举。本地项目不得套用 zip 的“剥掉唯一顶层目录”逻辑：

```python
        from app.core.indexing.walker import iter_local_project_files, strip_root_dir

        if repo.get("origin") != "local":
            root = strip_root_dir(root)
        await execute("UPDATE repos SET root_path = %s WHERE id = %s", (root, repo_id))

        if repo.get("origin") == "local":
            iterator = iter_local_project_files(root, settings.max_file_kb * 1024)
        else:
            iterator = iter_source_files(root, settings.max_file_kb * 1024)
        files = list(iterator)[: settings.max_repo_files]
```

在 `backend/app/api/v1/repos.py` 的 `get_repos` 之前加入：

```python
@router.post("/repos/local", response_model=RepoOut)
async def open_local_repo(
    body: RepoLocalCreate, user: dict = Depends(get_current_user)
):
    if not settings.is_local:
        raise HTTPException(status_code=404, detail="仅本地模式支持打开本地文件夹")
    try:
        return await register_local_project(user, body.path, body.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
```

在 `repos.py` 顶部加入：

```python
from app.local.projects import register_local_project
```

并把 `from app.models.schemas import (` 块中 `RepoImportGit,` 之后、`RepoOut,` 之前加入一行：

```python
    RepoLocalCreate,
```

在 `frontend/src/lib/types.ts` 的 `Repo` 类型中加入：

```ts
  origin?: 'upload' | 'git' | 'local'
```

- [ ] **Step 5: 实现 gitignore 感知 walker**

在 `backend/app/core/indexing/walker.py` 末尾加入：

```python
def _git_listed_files(root: Path) -> list[str] | None:
    """Tracked + untracked (non-ignored) files. None means fall back to walk."""
    git = shutil.which("git")
    if not git:
        return None
    try:
        result = subprocess.run(
            [
                git, "-C", str(root), "ls-files", "-z",
                "--cached", "--others", "--exclude-standard",
            ],
            capture_output=True, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return [p for p in result.stdout.decode("utf-8", "replace").split("\0") if p]


def iter_local_project_files(root: str, max_file_bytes: int):
    """Yield project files, honoring .gitignore; skip symlinks escaping root."""
    root_path = Path(root).resolve()
    listed = _git_listed_files(root_path)
    if listed is None:
        yield from iter_source_files(str(root_path), max_file_bytes)
        return
    for raw in listed:
        rel = raw.replace("\\", "/")
        if not is_supported(rel) or is_secret_path(rel):
            continue
        try:
            abspath = (root_path / rel).resolve(strict=True)
        except OSError:
            continue
        if root_path not in abspath.parents and abspath != root_path:
            continue
        if not abspath.is_file():
            continue
        try:
            size = abspath.stat().st_size
        except OSError:
            continue
        if size == 0 or size > max_file_bytes:
            continue
        if not rel.lower().endswith(".pdf"):
            try:
                head = abspath.open("rb").read(2048)
            except OSError:
                continue
            if looks_binary(head):
                continue
        yield rel, str(abspath), size
```

- [ ] **Step 6: 运行测试确认通过**

Run: `cd backend && NOVA_TEST_FAST=1 python -m pytest tests/test_local_projects.py tests/test_indexing.py -q`

Expected: PASS；gitignore 测试在无 git 的机器上跳过并给出明确理由。

- [ ] **Step 7: 重新生成 OpenAPI 契约**

Run:

```bash
cd backend && python -m scripts.export_openapi
cd ../frontend && npm run contract:generate && npm run contract:check
```

Expected: `wrote .../contracts/openapi.json`；`contract types up to date`。

- [ ] **Step 8: 全量回归与提交**

Run: `cd backend && NOVA_TEST_FAST=1 python -m pytest tests -q && ruff check app tests`

Expected: 全绿。

```bash
git add backend/app/local/projects.py backend/app/core/indexing/pipeline.py backend/app/core/indexing/walker.py backend/app/db/init_db.py backend/app/models/schemas.py backend/app/api/v1/repos.py backend/tests/test_local_projects.py frontend/src/lib/types.ts contracts/openapi.json frontend/src/lib/api-schema.d.ts
git commit -m "feat: open local folders as projects with gitignore-aware indexing"
```

---

## Task 7: HostExecutor 核心（路径 jail、环境剥离、进程树取消）

**Files:**
- Create: `backend/app/core/exec/__init__.py`
- Create: `backend/app/core/exec/host.py`
- Test: `backend/tests/test_host_executor.py`

**Interfaces:**
- Consumes: 无（只依赖标准库与 `app.local.pg.pid_alive` 的等价实现）。
- Produces:
  - `scrub_env(extra=None, *, env=None, platform=None) -> dict[str, str]`
  - `resolve_cwd(root: str | Path, cwd: str = ".") -> Path`
  - `build_shell_argv(command: str, *, platform: str | None = None) -> list[str]`
  - `project_python(root: str | Path) -> Path | None`
  - `async execute_host(command, *, root, cwd=".", timeout=120, stdin="", env=None, on_output=None, job_id=None, user_id=None, venv_root=None) -> dict`
  - `async kill_process_tree(pid: int) -> None`
  - `async cancel_host_processes(job_id, user_id=None) -> int`
  - `pid_alive(pid: int) -> bool`（本模块独立实现，避免循环依赖）

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_host_executor.py`：

```python
import asyncio
import os
import sys
from pathlib import Path

import pytest

from app.core.exec import host


def test_scrub_env_keeps_allowlisted_and_drops_secrets():
    env = {
        "PATH": "C:/Windows/System32",
        "SYSTEMROOT": "C:/Windows",
        "TEMP": "C:/Temp",
        "HOME": "C:/Users/alice",
        "AWS_PROFILE": "prod",
        "ZHIPU_API_KEY": "sk-secret",
        "NOVA_TOKEN": "token",
        "SECRET_KEY": "leak",
    }
    cleaned = host.scrub_env(env=env, platform="win32")
    assert cleaned["PATH"] == "C:/Windows/System32"
    assert cleaned["SYSTEMROOT"] == "C:/Windows"
    assert "AWS_PROFILE" not in cleaned
    assert "ZHIPU_API_KEY" not in cleaned
    assert "NOVA_TOKEN" not in cleaned
    assert "SECRET_KEY" not in cleaned


def test_scrub_env_filters_explicit_values():
    cleaned = host.scrub_env(
        {"PYTHONPATH": "C:/work", "MY_API_KEY": "secret", "NO_PROXY": "localhost"},
        env={"PATH": "C:/bin"},
        platform="win32",
    )
    assert cleaned["PYTHONPATH"] == "C:/work"
    assert cleaned["NO_PROXY"] == "localhost"
    assert "MY_API_KEY" not in cleaned


def test_resolve_cwd_accepts_subdirectory_with_spaces(tmp_path):
    child = tmp_path / "sub dir"
    child.mkdir()
    assert host.resolve_cwd(tmp_path, "sub dir") == child.resolve()


def test_resolve_cwd_rejects_traversal_and_absolute(tmp_path):
    with pytest.raises(ValueError, match="相对"):
        host.resolve_cwd(tmp_path, "..")
    with pytest.raises(ValueError, match="相对"):
        host.resolve_cwd(tmp_path, str(tmp_path))
    with pytest.raises(ValueError, match="相对"):
        host.resolve_cwd(tmp_path, "C:/Windows")


def test_build_shell_argv_uses_cmd_without_autorun(monkeypatch):
    monkeypatch.setenv("COMSPEC", r"C:\Windows\System32\cmd.exe")
    argv = host.build_shell_argv("echo hi", platform="win32")
    assert argv[1:] == ["/d", "/s", "/c", "echo hi"]
    assert argv[0].lower().endswith("cmd.exe")


def test_build_shell_argv_posix():
    assert host.build_shell_argv("echo hi", platform="linux") == ["/bin/sh", "-c", "echo hi"]


def test_project_python_detects_venv(tmp_path):
    python = tmp_path / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    python.parent.mkdir(parents=True)
    python.touch()
    assert host.project_python(tmp_path) == python


@pytest.mark.asyncio
async def test_execute_host_runs_command_and_marks_no_isolation(tmp_path):
    command = f'"{sys.executable}" -c "print(\'host-ok\')"'
    result = await host.execute_host(command, root=tmp_path, timeout=10)
    assert result["stdout"].strip() == "host-ok"
    assert result["exit_code"] == 0
    assert result["sandboxed"] is False
    assert result["isolation"] == "none"
    assert result["executor"] == "host"


@pytest.mark.asyncio
async def test_execute_host_strips_secret_env(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVA_TEST_TOKEN", "must-not-leak")
    command = (
        f'"{sys.executable}" -c '
        f'"import os; print(os.getenv(\'NOVA_TEST_TOKEN\', \'missing\'))"'
    )
    result = await host.execute_host(command, root=tmp_path, timeout=10)
    assert result["stdout"].strip() == "missing"


@pytest.mark.asyncio
async def test_execute_host_timeout_kills_process_tree(tmp_path):
    script = tmp_path / "spawn.py"
    script.write_text(
        "import subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "open(sys.argv[1], 'w').write(str(child.pid))\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )
    marker = tmp_path / "child.pid"
    command = f'"{sys.executable}" "{script}" "{marker}"'
    result = await host.execute_host(command, root=tmp_path, timeout=4)
    assert result["timed_out"] is True
    assert marker.is_file()
    child_pid = int(marker.read_text(encoding="utf-8"))
    for _ in range(50):
        if not host.pid_alive(child_pid):
            break
        await asyncio.sleep(0.1)
    assert not host.pid_alive(child_pid)


@pytest.mark.asyncio
async def test_cancel_host_processes_by_job_id(tmp_path):
    command = f'"{sys.executable}" -c "import time; time.sleep(60)"'
    task = asyncio.create_task(
        host.execute_host(command, root=tmp_path, timeout=30, job_id="job-1", user_id=7)
    )
    for _ in range(50):
        if host._RUNNING.get("job-1"):
            break
        await asyncio.sleep(0.05)
    killed = await host.cancel_host_processes("job-1", 7)
    result = await task
    assert killed == 1
    assert result["timed_out"] is False
    assert result["exit_code"] != 0


@pytest.mark.asyncio
async def test_cancel_host_processes_ignores_other_user(tmp_path):
    command = f'"{sys.executable}" -c "import time; time.sleep(2)"'
    task = asyncio.create_task(
        host.execute_host(command, root=tmp_path, timeout=30, job_id="job-2", user_id=7)
    )
    await asyncio.sleep(0.2)
    assert await host.cancel_host_processes("job-2", 99) == 0
    await task
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && NOVA_TEST_FAST=1 python -m pytest tests/test_host_executor.py -q`

Expected: FAIL — `ModuleNotFoundError: app.core.exec`。

- [ ] **Step 3: 实现 HostExecutor**

创建空文件 `backend/app/core/exec/__init__.py`。

创建 `backend/app/core/exec/host.py`：

```python
"""Host process execution for local mode.

No container, no uid change, no cgroup: commands run as the signed-in user.
The calling tool is responsible for policy/approval and for the explicit UX
warning. This module provides path containment, environment scrubbing, output
streaming, timeouts and process-tree cancellation.
"""
import asyncio
import os
import re
import subprocess
import sys
import time
from pathlib import Path

OUTPUT_LIMIT = 100_000
_DRIVE = re.compile(r"^[A-Za-z]:")

_WIN_ALLOW = {
    "PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC",
    "TEMP", "TMP", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "APPDATA",
    "LOCALAPPDATA", "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)",
    "NUMBER_OF_PROCESSORS", "OS", "PROCESSOR_ARCHITECTURE",
}
_POSIX_ALLOW = {
    "PATH", "HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "LC_CTYPE",
    "TERM", "TMPDIR", "SHELL",
}
_SECRET_MARKERS = ("API_KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")

_RUNNING: dict[str, set[tuple[int, str]]] = {}


def scrub_env(extra=None, *, env=None, platform=None) -> dict[str, str]:
    plat = platform or sys.platform
    source = dict(os.environ if env is None else env)
    allow = _WIN_ALLOW if plat == "win32" else _POSIX_ALLOW
    out = {
        key: value for key, value in source.items()
        if key in allow or key.upper() in allow
    }
    for key, value in (extra or {}).items():
        upper = key.upper()
        if any(marker in upper for marker in _SECRET_MARKERS):
            continue
        out[key] = str(value)
    out["PYTHONIOENCODING"] = "utf-8"
    out["PYTHONUTF8"] = "1"
    return out


def resolve_cwd(root: str | Path, cwd: str = ".") -> Path:
    root_path = Path(root).resolve(strict=True)
    raw = str(cwd or ".").strip()
    if "\x00" in raw:
        raise ValueError("cwd 包含非法字符")
    if raw.startswith(("/", "\\")) or _DRIVE.match(raw):
        raise ValueError("cwd 必须是相对项目根目录的路径")
    candidate = (root_path / raw).resolve(strict=False)
    if candidate != root_path and root_path not in candidate.parents:
        raise ValueError("cwd 越出项目目录")
    if not candidate.is_dir():
        raise ValueError(f"cwd 不存在：{raw}")
    return candidate


def build_shell_argv(command: str, *, platform: str | None = None) -> list[str]:
    if not command.strip():
        raise ValueError("command 不能为空")
    if "\x00" in command:
        raise ValueError("command 包含非法字符")
    if (platform or sys.platform) == "win32":
        comspec = os.environ.get("COMSPEC", r"C:\Windows\System32\cmd.exe")
        return [comspec, "/d", "/s", "/c", command]
    return ["/bin/sh", "-c", command]


def project_python(root: str | Path) -> Path | None:
    base = Path(root)
    candidates = [
        base / ".venv" / "Scripts" / "python.exe",
        base / ".venv" / "bin" / "python",
        base / "venv" / "Scripts" / "python.exe",
        base / "venv" / "bin" / "python",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _apply_project_venv(env: dict[str, str], root: Path) -> dict[str, str]:
    python = project_python(root)
    if python is not None:
        env["VIRTUAL_ENV"] = str(python.parent.parent)
        env["PATH"] = str(python.parent) + os.pathsep + env.get("PATH", "")
    return env


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
            return bool(ok) and code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _kill_tree_sync(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True, timeout=20,
        )
        return
    import signal

    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


async def kill_process_tree(pid: int) -> None:
    await asyncio.to_thread(_kill_tree_sync, pid)


def _register(job_id: str, pid: int, user_id) -> None:
    _RUNNING.setdefault(str(job_id), set()).add((pid, str(user_id)))


def _unregister(job_id: str, pid: int, user_id) -> None:
    entries = _RUNNING.get(str(job_id))
    if not entries:
        return
    entries.discard((pid, str(user_id)))
    if not entries:
        _RUNNING.pop(str(job_id), None)


async def cancel_host_processes(job_id, user_id=None) -> int:
    killed = 0
    for pid, owner in list(_RUNNING.get(str(job_id), set())):
        if user_id is not None and owner != str(user_id):
            continue
        await kill_process_tree(pid)
        killed += 1
    return killed


async def execute_host(
    command: str,
    *,
    root: str | Path,
    cwd: str = ".",
    timeout: int = 120,
    stdin: str = "",
    env: dict[str, str] | None = None,
    on_output=None,
    job_id: str | None = None,
    user_id=None,
    venv_root: str | Path | None = None,
) -> dict:
    workdir = resolve_cwd(root, cwd)
    argv = build_shell_argv(command)
    child_env = _apply_project_venv(
        scrub_env(env), Path(venv_root or root).resolve()
    )
    kwargs: dict = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True

    started = time.perf_counter()
    proc = await asyncio.create_subprocess_exec(
        *argv,
        cwd=str(workdir),
        env=child_env,
        stdin=asyncio.subprocess.PIPE if stdin else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        **kwargs,
    )
    if job_id:
        _register(str(job_id), proc.pid, user_id)

    stdout: list[str] = []
    stderr: list[str] = []

    async def pump(stream, sink: list[str], name: str) -> None:
        while True:
            chunk = await stream.readline()
            if not chunk:
                break
            text = chunk.decode("utf-8", "replace")
            remaining = OUTPUT_LIMIT - sum(len(part) for part in sink)
            if remaining > 0:
                sink.append(text[:remaining])
            if on_output is not None:
                on_output(name, text)

    pumps = [
        asyncio.create_task(pump(proc.stdout, stdout, "stdout")),
        asyncio.create_task(pump(proc.stderr, stderr, "stderr")),
    ]
    timed_out = False
    try:
        if stdin and proc.stdin is not None:
            try:
                proc.stdin.write(stdin.encode("utf-8"))
                await proc.stdin.drain()
                proc.stdin.close()
            except (BrokenPipeError, ConnectionResetError):
                pass
        try:
            await asyncio.wait_for(proc.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            timed_out = True
            await kill_process_tree(proc.pid)
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                pass
    finally:
        await asyncio.gather(*pumps, return_exceptions=True)
        if job_id:
            _unregister(str(job_id), proc.pid, user_id)

    return {
        "stdout": "".join(stdout),
        "stderr": "".join(stderr),
        "exit_code": proc.returncode if proc.returncode is not None else -1,
        "timed_out": timed_out,
        "sandboxed": False,
        "isolation": "none",
        "executor": "host",
        "command": command,
        "duration_ms": int((time.perf_counter() - started) * 1000),
    }
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && NOVA_TEST_FAST=1 python -m pytest tests/test_host_executor.py -q`

Expected: PASS，10 passed。Windows 上进程树测试实际走 `taskkill /T /F`；POSIX 走 `killpg`。

- [ ] **Step 5: 全量回归与提交**

Run: `cd backend && NOVA_TEST_FAST=1 python -m pytest tests -q && ruff check app tests`

Expected: 全绿。

```bash
git add backend/app/core/exec/__init__.py backend/app/core/exec/host.py backend/tests/test_host_executor.py
git commit -m "feat: add host executor with path jail and process-tree cancellation"
```

---

## Task 8: 工具层接入 HostExecutor（run_command / run_code / 状态 / 取消）

**Files:**
- Create: `backend/app/core/exec/service.py`
- Modify: `backend/app/core/tools/run_command.py`
- Modify: `backend/app/core/tools/run_code.py`
- Modify: `backend/app/core/sandbox/runtime.py`
- Modify: `backend/app/core/agent/loop.py`
- Test: `backend/tests/test_host_tools.py`

**Interfaces:**
- Consumes: Task 7 的 `execute_host` / `cancel_host_processes`；`settings.use_host_executor`。
- Produces:
  - `run_command_host(command, *, root, timeout, on_output=None, job_id=None, user_id=None) -> dict`
  - `run_code_host(files, command, *, root, timeout=120, env=None, on_output=None, job_id=None, user_id=None) -> dict`
  - 工具结果统一包含 `sandboxed: false`、`isolation: "none"`、`executor: "host"`、`warning`。
  - `sandbox_status()` 本地返回 `{available: True, executor: "host", isolation: "none"}`。
  - `kill_job_containers()` 本地调用 `cancel_host_processes()`。

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_host_tools.py`：

```python
import sys
from pathlib import Path

import pytest

from app.config import settings
from app.core.exec import service
from app.core.sandbox import runtime as sandbox_runtime
from app.core.tools.base import ToolContext
from app.core.tools import run_command as run_command_tool


def _ctx(user_id=1, **kwargs) -> ToolContext:
    return ToolContext(
        user={"id": user_id, "username": "local", "role": "local"},
        repo_ids=["00000000-0000-0000-0000-000000000001"],
        repo_roots={},
        session_id="00000000-0000-0000-0000-000000000002",
        **kwargs,
    )


@pytest.mark.asyncio
async def test_sandbox_status_local_reports_host(monkeypatch):
    monkeypatch.setattr(settings, "nova_mode", "local")
    status = await sandbox_runtime.sandbox_status()
    assert status["available"] is True
    assert status["executor"] == "host"
    assert status["isolation"] == "none"


@pytest.mark.asyncio
async def test_kill_job_containers_local_uses_host_registry(monkeypatch):
    monkeypatch.setattr(settings, "nova_mode", "local")
    calls: list[tuple] = []

    async def fake_cancel(job_id, user_id=None):
        calls.append((job_id, user_id))
        return 2

    monkeypatch.setattr("app.core.exec.host.cancel_host_processes", fake_cancel)
    assert await sandbox_runtime.kill_job_containers("tool-1", 7) == 2
    assert calls == [("tool-1", 7)]


@pytest.mark.asyncio
async def test_run_command_host_marks_result(monkeypatch, tmp_path):
    seen: dict = {}

    async def fake_execute(command, **kwargs):
        seen.update(command=command, **kwargs)
        return {
            "stdout": "ok", "stderr": "", "exit_code": 0, "timed_out": False,
            "sandboxed": False, "isolation": "none", "executor": "host",
            "command": command, "duration_ms": 1,
        }

    monkeypatch.setattr(service, "execute_host", fake_execute)
    result = await service.run_command_host(
        "echo ok", root=tmp_path, timeout=5, job_id="tool-9", user_id=7
    )
    assert seen["job_id"] == "tool-9"
    assert seen["user_id"] == 7
    assert result["sandboxed"] is False
    assert result["isolation"] == "none"
    assert "无容器隔离" in result["warning"]


@pytest.mark.asyncio
async def test_run_command_local_branch_executes_in_project(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(settings, "nova_data_dir", str(tmp_path / "NovaData"))

    async def fake_get_repo(repo_id, user_id):
        return {"id": repo_id, "root_path": str(tmp_path), "origin": "local"}

    monkeypatch.setattr("app.core.indexing.pipeline.get_repo", fake_get_repo)
    command = f'"{sys.executable}" -c "print(42)"'
    result = await run_command_tool.run_command(
        {"command": command, "repo_id": "00000000-0000-0000-0000-000000000001"},
        _ctx(),
    )
    assert result["stdout"].strip() == "42"
    assert result["persisted"] is True
    assert result["isolation"] == "none"
    assert result["warning"]


@pytest.mark.asyncio
async def test_run_code_host_writes_temp_and_cleans_it(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(settings, "nova_data_dir", str(tmp_path / "NovaData"))
    seen: dict = {}

    async def fake_execute(command, **kwargs):
        seen.update(command=command, **kwargs)
        assert (Path(kwargs["root"]) / "main.py").read_text(encoding="utf-8") == "print('x')"
        return {
            "stdout": "x", "stderr": "", "exit_code": 0, "timed_out": False,
            "sandboxed": False, "isolation": "none", "executor": "host",
            "command": command, "duration_ms": 1,
        }

    monkeypatch.setattr(service, "execute_host", fake_execute)
    result = await service.run_code_host(
        {"main.py": "print('x')"}, None, root=tmp_path, timeout=5
    )
    assert seen["command"] == "python main.py"
    assert result["isolation"] == "none"
    assert list((tmp_path / "NovaData" / "tmp").iterdir()) == []


@pytest.mark.asyncio
async def test_run_code_host_rejects_secret_and_traversal(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(settings, "nova_data_dir", str(tmp_path / "NovaData"))
    written: list[str] = []

    async def fake_execute(command, **kwargs):
        root = Path(kwargs["root"])
        written.extend(p.name for p in root.rglob("*"))
        return {
            "stdout": "", "stderr": "", "exit_code": 0, "timed_out": False,
            "sandboxed": False, "isolation": "none", "executor": "host",
            "command": command, "duration_ms": 1,
        }

    monkeypatch.setattr(service, "execute_host", fake_execute)
    await service.run_code_host(
        {"../escape.py": "x", ".env": "SECRET=1", "safe.py": "print(1)"},
        "python safe.py", root=tmp_path, timeout=5,
    )
    assert "safe.py" in written
    assert "escape.py" not in written
    assert ".env" not in written
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && NOVA_TEST_FAST=1 python -m pytest tests/test_host_tools.py -q`

Expected: FAIL — `ImportError: cannot import name 'service'`；`sandbox_status` 本地仍尝试 Docker。

- [ ] **Step 3: 实现执行服务**

创建 `backend/app/core/exec/service.py`：

```python
"""Tool-facing host execution helpers."""
import shutil
import uuid
from pathlib import Path

from app.config import settings
from app.core.exec.host import execute_host
from app.core.security.paths import is_secret_path, try_normalize_relpath

WARNING = "本地执行无容器隔离：命令以当前 Windows 用户权限在你的项目目录运行"


async def run_command_host(
    command: str,
    *,
    root: str | Path,
    timeout: int,
    on_output=None,
    job_id: str | None = None,
    user_id=None,
) -> dict:
    result = await execute_host(
        command,
        root=root,
        timeout=timeout,
        on_output=on_output,
        job_id=job_id,
        user_id=user_id,
    )
    result["warning"] = WARNING
    result["persisted"] = True
    result["isolated"] = False
    return result


def _safe_files(files: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw_path, content in (files or {}).items():
        rel = try_normalize_relpath(str(raw_path))
        if not rel or is_secret_path(rel):
            continue
        if not isinstance(content, str):
            continue
        out[rel] = content
    return out


async def run_code_host(
    files: dict,
    command: str | None,
    *,
    root: str | Path,
    timeout: int = 120,
    env: dict[str, str] | None = None,
    on_output=None,
    job_id: str | None = None,
    user_id=None,
) -> dict:
    payload = _safe_files(files)
    base = settings.local_tmp_root / f"run-{uuid.uuid4().hex}"
    base.mkdir(parents=True, exist_ok=False)
    try:
        for rel, content in payload.items():
            target = base / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        result = await execute_host(
            command or "python main.py",
            root=base,
            timeout=timeout,
            env=env,
            on_output=on_output,
            job_id=job_id,
            user_id=user_id,
            venv_root=root,
        )
        result["warning"] = WARNING
        result["workspace"] = "temporary"
        return result
    finally:
        shutil.rmtree(base, ignore_errors=True)
```

修改 `backend/app/core/sandbox/runtime.py` 的 `sandbox_status`，第一行加入：

```python
    if settings.use_host_executor:
        return {
            "available": True,
            "reason": "",
            "executor": "host",
            "isolation": "none",
            "docker": False,
            "default_available": True,
            "builder_available": True,
            "node_available": True,
            "warning": "本地执行无容器隔离",
        }
```

修改 `kill_job_containers`，第一行加入：

```python
    if settings.is_local:
        from app.core.exec.host import cancel_host_processes
        return await cancel_host_processes(job_id, user_id)
```

- [ ] **Step 4: 接入 `run_command`**

在 `backend/app/core/tools/run_command.py` 的 `run_command` 中，`root` 校验之后、`status = await sandbox_status()` 之前加入：

```python
    if settings.use_host_executor:
        return await _run_host_command(command, root=root, ctx=ctx, args=args)
```

在文件末尾、`TOOL = ToolDefinition(...)` 之前加入：

```python
async def _run_host_command(
    command: str, *, root: Path, ctx: ToolContext, args: dict
) -> dict:
    from app.core.exec.service import run_command_host

    on_output = None
    if ctx.output_queue is not None:
        loop = asyncio.get_running_loop()
        queue_ref = ctx.output_queue

        def on_output(stream: str, text: str) -> None:
            loop.call_soon_threadsafe(queue_ref.put_nowait, (stream, text))

    result = await run_command_host(
        command,
        root=root,
        timeout=min(int(args.get("timeout") or 120), 300),
        on_output=on_output,
        job_id=ctx.tool_call_id or None,
        user_id=ctx.user.get("id"),
    )
    await log_audit(
        AuditAction.SANDBOX_RUN,
        user_id=str(ctx.user.get("id", "")) if ctx.user else "anonymous",
        details={
            "executor": "host",
            "command": result.get("command"),
            "exit_code": result.get("exit_code"),
            "timed_out": result.get("timed_out"),
            "persisted": True,
            "isolated": False,
        },
    )
    ok = result["exit_code"] == 0 and not result["timed_out"]
    return {
        "exit_code": result["exit_code"],
        "timed_out": result["timed_out"],
        "stdout": result["stdout"],
        "stderr": result["stderr"],
        "command": result["command"],
        "persisted": True,
        "isolated": False,
        "sandboxed": False,
        "isolation": "none",
        "executor": "host",
        "warning": result["warning"],
        "hint": (
            "命令已在你的项目目录真实执行；如需保留改动请检查 git diff"
            if ok else
            "执行失败：请阅读 stderr，修正命令后重试"
        ),
    }
```

- [ ] **Step 5: 接入 `run_code`**

在 `run_code.py` 的风险扫描之后、`status = await sandbox_status()` 之前加入：

```python
    if settings.use_host_executor:
        return await _run_host_code(files, args, ctx, repo_id, copy_stats)
```

在文件末尾、`TOOL = ToolDefinition(...)` 之前加入：

```python
async def _run_host_code(
    files: dict, args: dict, ctx: ToolContext, repo_id: str | None,
    copy_stats: dict | None,
) -> dict:
    from app.core.exec.service import run_code_host
    from app.core.indexing.pipeline import get_repo

    env_kind = args.get("env")
    command = args.get("command")
    if env_kind == "node":
        command = command or "node main.js"
    else:
        command = command or "python main.py"

    root = settings.data_root
    if repo_id:
        repo = await get_repo(str(repo_id), ctx.user["id"])
        if not repo:
            raise ToolBusinessError("仓库不存在或无权访问")
        root = Path(repo["root_path"])

    on_output = None
    if ctx.output_queue is not None:
        loop = asyncio.get_running_loop()
        queue_ref = ctx.output_queue

        def on_output(stream: str, text: str) -> None:
            loop.call_soon_threadsafe(queue_ref.put_nowait, (stream, text))

    result = await run_code_host(
        files,
        command,
        root=root,
        timeout=min(settings.sandbox_timeout, 300),
        env=None,
        on_output=on_output,
        job_id=ctx.tool_call_id or None,
        user_id=ctx.user.get("id"),
    )
    await log_audit(
        AuditAction.SANDBOX_RUN,
        user_id=str(ctx.user.get("id", "")) if ctx.user else "anonymous",
        details={
            "executor": "host",
            "command": result.get("command"),
            "exit_code": result.get("exit_code"),
            "timed_out": result.get("timed_out"),
        },
    )
    payload = {
        "exit_code": result["exit_code"],
        "timed_out": result["timed_out"],
        "stdout": result["stdout"],
        "stderr": result["stderr"],
        "command": result["command"],
        "env": "host",
        "sandboxed": False,
        "isolation": "none",
        "executor": "host",
        "warning": result["warning"],
        "hint": "退出码 0 表示成功" if result["exit_code"] == 0 else "执行失败：请阅读 stderr，修正后重试",
    }
    if copy_stats is not None:
        payload["repo_copy"] = copy_stats
        if copy_stats.get("truncated"):
            payload["repo_copy_truncated"] = True
            payload["hint"] += " 仓库文件超过主机执行复制上限，测试结果可能不完整。"
    return payload
```

`args.get("env")` 是 `"node" | "slim" | "builder"`，不是环境变量字典，因此 `run_code_host` 的 `env` 参数固定传 `None`，仅根据 `env_kind` 选择默认命令。`command` 为 `node main.js` 时主机需要安装 Node（主机 PATH，缺失时以 exit 127 返回）。在 `run_code.py` 顶部补 `import asyncio`，因为本地分支与现有流式分支都使用它。

- [ ] **Step 6: 本地隐藏 bridge 工具**

修改 `backend/app/core/agent/loop.py` 的工具列表构造：

```python
    local_available = False if settings.is_local else await local_agent_online(user["id"])
    specs = registry.specs(
        permission_mode=ctx.permission_mode,
        local_available=local_available,
    )
```

- [ ] **Step 7: 运行测试确认通过**

Run: `cd backend && NOVA_TEST_FAST=1 python -m pytest tests/test_host_tools.py tests/test_sandbox_runtime.py tests/test_policy.py -q`

Expected: PASS；现有沙箱/策略测试不回归。

- [ ] **Step 8: 全量回归与提交**

Run: `cd backend && NOVA_TEST_FAST=1 python -m pytest tests -q && ruff check app tests`

Expected: 全绿。注意：本 Task 不新增 HTTP schema，无需重新导出契约。

```bash
git add backend/app/core/exec/service.py backend/app/core/tools/run_command.py backend/app/core/tools/run_code.py backend/app/core/sandbox/runtime.py backend/app/core/agent/loop.py backend/tests/test_host_tools.py
git commit -m "feat: execute run_command and run_code on the local host"
```

---

## Task 9: 本地验证、红绿任务与依赖安装门禁

**Files:**
- Modify: `backend/app/core/exec/service.py`（新增 `run_staged_host`）
- Modify: `backend/app/core/verify/service.py`
- Modify: `backend/app/core/tasks/engine.py`
- Modify: `backend/app/core/tools/install_deps.py`
- Modify: `backend/app/core/security/policy.py`
- Test: `backend/tests/test_local_verify.py`

**Interfaces:**
- Consumes: Task 7 的 `execute_host`；Task 8 的 `_safe_files`。
- Produces:
  - `run_staged_host(files, command, *, root, timeout=180, job_id=None, user_id=None) -> dict`：把暂存文件写入数据目录临时工作区，使用项目 `.venv` 的 PATH 执行，结束后删除临时目录。
  - `POST /repos/{id}/verify` 在本地走 `run_staged_host`，结果 `image: "host"`。
  - `/fix` 红绿在本地走临时工作区。
  - `install_deps` 本地默认拒绝；显式开启且审批通过后，只使用项目 `.venv`/npm 在项目根目录执行。

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_local_verify.py`：

```python
import sys
from types import SimpleNamespace

import pytest

from app.config import settings
from app.core import tasks
from app.core.exec import service
from app.core.security import policy
from app.core.tools import install_deps as install_deps_tool
from app.core.tools.base import ToolBusinessError, ToolContext
from app.core.verify import service as verify_service


def _ctx(**kwargs) -> ToolContext:
    return ToolContext(
        user={"id": 1, "username": "local", "role": "local"},
        repo_ids=["00000000-0000-0000-0000-000000000001"],
        permission_mode="ask",
        **kwargs,
    )


class _Step:
    name = "单元测试"
    command = "python -m pytest -q"
    timeout = 60
    required = True
    image = "python"
    network = False


@pytest.mark.asyncio
async def test_verification_uses_host_workspace(monkeypatch, tmp_path):
    profile = SimpleNamespace(
        stack="python", steps=[_Step()], notes=[], unsupported_reason=None
    )
    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(verify_service, "detect_profile", lambda files: profile)

    async def fake_collect(repo_id, user):
        return {"app.py": "print(1)"}

    async def fake_run_staged(files, command, **kwargs):
        assert kwargs["root"] == str(tmp_path)
        return {"exit_code": 0, "stdout": "ok", "stderr": "", "timed_out": False,
                "isolation": "none", "warning": "无容器隔离"}

    monkeypatch.setattr(verify_service, "_collect_repo_files", fake_collect)
    monkeypatch.setattr(verify_service, "run_staged_host", fake_run_staged)
    result = await verify_service.run_verification(
        {"id": "r1", "root_path": str(tmp_path)}, {"id": 1}
    )
    assert result["status"] == "passed"
    assert result["image"] == "host"
    assert "无容器隔离" in " ".join(result["notes"])


@pytest.mark.asyncio
async def test_run_staged_host_runs_pytest_in_temp_workspace(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(settings, "nova_data_dir", str(tmp_path / "NovaData"))
    files = {"test_sample.py": "def test_ok():\n    assert 1 + 1 == 2\n"}
    result = await service.run_staged_host(
        files,
        f'"{sys.executable}" -m pytest -q',
        root=tmp_path,
        timeout=60,
    )
    assert result["exit_code"] == 0
    assert result["isolation"] == "none"
    assert list((tmp_path / "NovaData" / "tmp").iterdir()) == []


@pytest.mark.asyncio
async def test_task_sandbox_run_uses_host(monkeypatch, tmp_path):
    called: dict = {}

    async def fake_run_staged(files, command, **kwargs):
        called.update(files=files, command=command, **kwargs)
        return {"exit_code": 1, "stdout": "", "stderr": "red", "timed_out": False}

    async def fake_audit(*args, **kwargs):
        return None

    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr("app.core.tasks.engine.run_staged_host", fake_run_staged)
    monkeypatch.setattr("app.core.tasks.engine.log_audit", fake_audit)
    result = await tasks.engine._sandbox_run(
        "task-1", {"id": 1}, "repo-1", tmp_path,
        {"app.py": "print(1)"}, {"test_app.py": "def test_x(): pass"},
        "python -m pytest -q",
    )
    assert result["exit_code"] == 1
    assert called["root"] == tmp_path
    assert called["command"] == "python -m pytest -q"


@pytest.mark.asyncio
async def test_install_deps_local_disabled_by_default(monkeypatch):
    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(settings, "local_allow_install_deps", False)
    with pytest.raises(ToolBusinessError, match="默认禁用"):
        await install_deps_tool.install_deps({}, _ctx())


@pytest.mark.asyncio
async def test_install_deps_local_requires_approval(monkeypatch):
    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(settings, "local_allow_install_deps", True)
    with pytest.raises(ToolBusinessError, match="批准"):
        await install_deps_tool.install_deps({}, _ctx(approval_granted=False))


@pytest.mark.asyncio
async def test_install_deps_local_uses_project_venv(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(settings, "local_allow_install_deps", True)
    (tmp_path / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    seen: dict = {}

    async def fake_get_repo(repo_id, user_id):
        return {"id": repo_id, "root_path": str(tmp_path), "origin": "local"}

    def fake_read(root, rel):
        return "pytest\n"

    async def fake_execute(command, **kwargs):
        seen.update(command=command, **kwargs)
        return {"exit_code": 0, "stdout": "installed", "stderr": "",
                "timed_out": False, "isolation": "none"}

    async def fake_audit(*args, **kwargs):
        return None

    monkeypatch.setattr(install_deps_tool, "get_repo", fake_get_repo)
    monkeypatch.setattr(install_deps_tool, "_read_repo_file", fake_read)
    monkeypatch.setattr(install_deps_tool, "project_python", lambda root: tmp_path / "python.exe")
    monkeypatch.setattr(install_deps_tool, "execute_host", fake_execute)
    monkeypatch.setattr(install_deps_tool, "log_audit", fake_audit)
    result = await install_deps_tool.install_deps({}, _ctx(approval_granted=True))
    assert result["installed"] is True
    assert str(tmp_path / "python.exe") in seen["command"]
    assert "-m pip install -r" in seen["command"]


def test_policy_local_install_deps_requires_approval(monkeypatch):
    from app.config import settings as live_settings

    monkeypatch.setattr(live_settings, "nova_mode", "local")
    monkeypatch.setattr(live_settings, "local_allow_install_deps", False)
    denied = policy.decide_tool("install_deps", "execute", None, {}, _ctx())
    assert denied.allowed is False
    assert "默认禁用" in denied.reason

    monkeypatch.setattr(live_settings, "local_allow_install_deps", True)
    approval = policy.decide_tool("install_deps", "execute", None, {}, _ctx())
    assert approval.allowed is False
    assert approval.requires_approval is True
    allowed = policy.decide_tool(
        "install_deps", "execute", None, {}, _ctx(approval_granted=True)
    )
    assert allowed.allowed is True
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && NOVA_TEST_FAST=1 python -m pytest tests/test_local_verify.py -q`

Expected: FAIL — `AttributeError: module ... has no attribute 'run_staged_host'`；`_sandbox_run` 仍要求 Docker。

- [ ] **Step 3: 实现 `run_staged_host`**

在 `backend/app/core/exec/service.py` 末尾加入：

```python
async def run_staged_host(
    files: dict,
    command: str,
    *,
    root: str | Path,
    timeout: int = 180,
    job_id: str | None = None,
    user_id=None,
) -> dict:
    payload = _safe_files(files)
    base = settings.local_tmp_root / f"stage-{uuid.uuid4().hex}"
    base.mkdir(parents=True, exist_ok=False)
    try:
        for rel, content in payload.items():
            target = base / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        result = await execute_host(
            command,
            root=base,
            timeout=timeout,
            job_id=job_id,
            user_id=user_id,
            venv_root=root,
        )
        result["warning"] = WARNING
        result["workspace"] = "temporary"
        return result
    finally:
        shutil.rmtree(base, ignore_errors=True)
```

- [ ] **Step 4: 本地 verify 分支**

在 `backend/app/core/verify/service.py` 顶部导入：

```python
from app.core.exec.service import run_staged_host
```

在 `run_verification` 的 `if not profile.steps:` 块之后加入：

```python
    if settings.use_host_executor:
        return await _run_verification_host(repo, files, profile, started, now)
```

在文件末尾加入：

```python
async def _run_verification_host(repo: dict, files: dict, profile, started: float, now: str) -> dict:
    notes = list(profile.notes) + ["本地模式在主机执行，无容器隔离"]
    steps: list[dict] = []
    stopped_early = False
    for index, step in enumerate(profile.steps):
        step_started = time.perf_counter()
        result = await run_staged_host(
            files,
            step.command,
            root=repo["root_path"],
            timeout=step.timeout,
        )
        exit_code = result.get("exit_code", -1)
        timed_out = bool(result.get("timed_out"))
        if timed_out:
            step_status = "failed"
        elif exit_code == 127 and not step.required:
            step_status = "skipped"
        elif exit_code == 0:
            step_status = "passed"
        else:
            step_status = "failed"
        steps.append({
            "name": step.name,
            "command": step.command,
            "required": step.required,
            "status": step_status,
            "exit_code": exit_code,
            "timed_out": timed_out,
            "stdout": _tail(result.get("stdout"), 4000),
            "stderr": _tail(result.get("stderr"), 1500),
            "duration_ms": int((time.perf_counter() - step_started) * 1000),
        })
        if step_status == "failed" and not step.required:
            notes.append(f"「{step.name}」失败（非必需步骤，不阻断通过）")
        if step_status == "failed" and step.required:
            if index < len(profile.steps) - 1:
                notes.append(f"「{step.name}」失败，后续检查已跳过")
            stopped_early = True
            break

    required = [s for s in steps if s["required"]]
    failed = [s for s in required if s["status"] == "failed"]
    passed = [s for s in steps if s["status"] == "passed"]
    overall = "failed" if failed else "passed" if passed else "unsupported"
    if stopped_early:
        overall = "failed"
    first_failure = next(
        (s for s in steps if s["status"] == "failed" and s["required"]), None
    )
    stdout = "\n\n".join(f"$ {s['command']}\n{s['stdout']}" for s in steps if s["stdout"])
    stderr = "\n\n".join(f"$ {s['command']}\n{s['stderr']}" for s in steps if s["stderr"])
    logger.info(
        "verification_done", repo_id=str(repo["id"]), stack=profile.stack,
        status=overall, steps=len(steps), executor="host",
    )
    return {
        "status": overall,
        "stack": profile.stack,
        "notes": notes,
        "steps": steps,
        "exit_code": first_failure["exit_code"] if first_failure else 0,
        "stdout": stdout[-6000:],
        "stderr": stderr[-3000:],
        "command": " → ".join(step.command for step in profile.steps),
        "image": "host",
        "at": now,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
    }
```

- [ ] **Step 5: 任务引擎红绿走主机工作区**

在 `backend/app/core/tasks/engine.py` 顶部导入：

```python
from app.core.exec.service import run_staged_host
```

修改 `_sandbox_run` 签名为：

```python
async def _sandbox_run(
    task_id: str, user: dict, repo_id: str, root: Path,
    repo_files: dict[str, str], extra: dict[str, str], command: str,
    ctx=None,
) -> dict:
```

在其开头、`check_sandbox_quota` 之前加入：

```python
    if settings.use_host_executor:
        if ctx:
            await ctx.update(step="主机验证")
        result = await run_staged_host(
            {**repo_files, **extra},
            command,
            root=root,
            timeout=max(settings.sandbox_timeout, 120),
            job_id=ctx.job_id if ctx else None,
        )
        if ctx:
            await ctx.check_cancel()
        await log_audit(
            AuditAction.SANDBOX_RUN,
            user_id=str(user.get("id", "")),
            details={
                "task_id": task_id, "command": command,
                "exit_code": result.get("exit_code"), "executor": "host",
            },
        )
        return result
```

在 `run_task` 的 sandbox 可用性检查处改为：

```python
        if not settings.use_host_executor:
            status = await sandbox_status()
            if not status["available"]:
                raise RuntimeError(f"沙箱不可用：{status['reason']}")
```

把三处调用改为传入 `root`：

```python
        red = await _sandbox_run(task_id, user, str(repo_id), root, repo_files, test_files, red_command, ctx=ctx)
```

```python
        green = await _sandbox_run(task_id, user, str(repo_id), root, repo_files, {**test_files, **fix_files}, green_command, ctx=ctx)
```

```python
            green = await _sandbox_run(task_id, user, str(repo_id), root, repo_files, {**test_files, **fix_files}, green_command, ctx=ctx)
```

- [ ] **Step 6: 依赖安装本地门禁**

在 `backend/app/core/security/policy.py` 的 `decide_tool` 中，`if name == "install_deps":` 之前加入：

```python
    if name == "install_deps" and settings.is_local:
        if not settings.local_allow_install_deps:
            return PolicyDecision(
                False,
                "本地模式默认禁用依赖安装；如需开启，请在 nova-config.json 设置 allowInstallDeps=true 后重启",
                caps,
            )
        if not getattr(ctx, "approval_granted", False):
            return PolicyDecision(
                False, "本地安装依赖需要你批准后才会执行", caps, requires_approval=True
            )
        return PolicyDecision(True, "allowed", caps)
```

在 `backend/app/core/tools/install_deps.py` 顶部导入：

```python
from app.core.exec.host import execute_host, project_python
from app.core.security.paths import try_normalize_relpath
```

在 `install_deps` 函数第一行加入：

```python
    if settings.is_local:
        return await _install_deps_local(args, ctx)
```

在文件末尾、`TOOL = ToolDefinition(...)` 之前加入：

```python
async def _install_deps_local(args: dict, ctx: ToolContext) -> dict:
    if not settings.local_allow_install_deps:
        raise ToolBusinessError(
            "本地模式默认禁用依赖安装；如需开启，请在 nova-config.json 设置 allowInstallDeps=true 后重启"
        )
    if not getattr(ctx, "approval_granted", False):
        raise ToolBusinessError("本地安装依赖需要你批准")

    repo_id = args.get("repo_id") or (ctx.repo_ids[0] if ctx.repo_ids else None)
    if not repo_id:
        raise ToolBusinessError("需要指定 repo_id，或先在会话中关联仓库")
    repo = await get_repo(str(repo_id), ctx.user["id"])
    if not repo:
        raise ToolBusinessError("仓库不存在或无权访问")
    root = Path(repo["root_path"]).resolve()

    kind = "node" if str(args.get("kind") or "").lower() == "node" else "python"
    default_manifest = "package.json" if kind == "node" else "requirements.txt"
    raw_rel = str(args.get("requirements") or default_manifest)
    rel = try_normalize_relpath(raw_rel)
    if not rel or '"' in rel or "\x00" in rel:
        raise ToolBusinessError("依赖文件路径不安全")
    if kind == "node" and rel.lower().endswith("requirements.txt"):
        kind = "python"

    if kind == "python":
        python = project_python(root)
        if python is None:
            raise ToolBusinessError(
                "未找到项目虚拟环境 .venv；请先在项目目录创建 .venv 并安装 pip"
            )
        if _read_repo_file(root, rel) is None:
            raise ToolBusinessError(f"未找到依赖文件：{rel}")
        command = f'"{python}" -m pip install -r "{rel}"'
    else:
        if "/" in rel:
            raise ToolBusinessError("Node 依赖安装目前只支持仓库根目录 package.json")
        files: dict[str, str] = {}
        manifest = _read_repo_file(root, rel)
        if manifest is None:
            raise ToolBusinessError(f"未找到 Node 依赖文件：{rel}")
        for lock in NODE_LOCKFILES:
            content = _read_repo_file(root, lock)
            if content is not None:
                files[lock] = content
        if "pnpm-lock.yaml" in files:
            command = "corepack pnpm install --frozen-lockfile"
        elif "yarn.lock" in files:
            command = "corepack yarn install --immutable"
        elif "package-lock.json" in files:
            command = "npm ci --no-audit --no-fund"
        else:
            command = "npm install --no-audit --no-fund"

    result = await execute_host(
        command,
        root=root,
        timeout=max(settings.sandbox_install_timeout, 300),
        user_id=ctx.user.get("id"),
    )
    await log_audit(
        AuditAction.SANDBOX_RUN,
        user_id=str(ctx.user.get("id", "")),
        details={
            "action": "install_deps", "kind": kind, "repo_id": str(repo_id),
            "manifest": rel, "exit_code": result.get("exit_code"),
            "executor": "host",
        },
    )
    tail = (result.get("stdout", "") + "\n" + result.get("stderr", ""))[-4000:]
    if result.get("exit_code") != 0:
        raise ToolBusinessError(
            f"依赖安装失败（exit {result.get('exit_code')}）：\n{tail[-1500:]}"
        )
    return {
        "installed": True,
        "kind": kind,
        "manifest": rel,
        "command": command,
        "output_tail": tail[-1500:],
        "isolation": "none",
        "hint": "依赖已安装到项目自身的 .venv / node_modules；后续验证直接使用。",
    }
```

- [ ] **Step 7: 运行测试确认通过**

Run: `cd backend && NOVA_TEST_FAST=1 python -m pytest tests/test_local_verify.py tests/test_verify.py tests/test_policy.py -q`

Expected: PASS，包含真实 `pytest` 临时工作区测试。

- [ ] **Step 8: 全量回归与提交**

Run: `cd backend && NOVA_TEST_FAST=1 python -m pytest tests -q && ruff check app tests`

Expected: 全绿。

```bash
git add backend/app/core/exec/service.py backend/app/core/verify/service.py backend/app/core/tasks/engine.py backend/app/core/tools/install_deps.py backend/app/core/security/policy.py backend/tests/test_local_verify.py
git commit -m "feat: run local verification and red-green tasks on the host"
```

---

## Task 10: 无 Qdrant 检索降级与 `/status/mode`

**Files:**
- Modify: `backend/app/core/rag/dense.py`
- Modify: `backend/app/core/rag/retriever.py`
- Modify: `backend/app/models/schemas.py`
- Modify: `backend/app/api/v1/status.py`
- Test: `backend/tests/test_local_retrieval.py`
- Regenerate: `contracts/openapi.json`、`frontend/src/lib/api-schema.d.ts`

**Interfaces:**
- Consumes: `settings.use_embeddings`；`settings.local_user`。
- Produces:
  - `dense_search` 在 `use_embeddings=false` 时返回 `[]`，不构造 embedder/Qdrant client。
  - `retrieve` 本地只走 keyword leg，返回的 `RetrievedChunk` 仍含 `path`/`line_start`/`line_end`。
  - `GET /api/v1/status/mode` → `ModeOut`，无认证。
  - 本地 `/status/health` 中 `qdrant`/`embedding` 显示 `disabled: local mode`，不拉低 `core_ok`。

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_local_retrieval.py`：

```python
from unittest.mock import AsyncMock

import pytest

from app.config import settings
from app.core.rag import dense, retriever
from app.db import init_db
from app.models.domain import RetrievedChunk


@pytest.mark.asyncio
async def test_dense_search_short_circuits_without_embeddings(monkeypatch):
    monkeypatch.setattr(settings, "nova_mode", "local")

    def boom():
        raise AssertionError("embedder must not be constructed in local mode")

    monkeypatch.setattr(dense, "get_embedder", boom)
    assert await dense.dense_search("query", repo_ids=["00000000-0000-0000-0000-000000000001"]) == []


@pytest.mark.asyncio
async def test_index_embedding_is_skipped_in_local_mode(monkeypatch):
    from app.core.indexing import pipeline

    monkeypatch.setattr(settings, "nova_mode", "local")
    constructed = False

    def boom():
        nonlocal constructed
        constructed = True
        raise AssertionError("embedder must not be constructed during local indexing")

    monkeypatch.setattr("app.core.embedding.embedder.get_embedder", boom)
    assert await pipeline._embed_and_upload(
        "00000000-0000-0000-0000-000000000001", 1,
        [(1, {"content": "def f(): pass"}, "hash")],
    ) == 0
    assert constructed is False


@pytest.mark.asyncio
async def test_retrieve_uses_keyword_only_in_local_mode(monkeypatch):
    called = {"dense": 0, "keyword": 0}

    async def fake_dense(*args, **kwargs):
        called["dense"] += 1
        return []

    async def fake_keyword(*args, **kwargs):
        called["keyword"] += 1
        return [RetrievedChunk(
            id="c1", content="def handler(): pass", path="app.py",
            line_start=10, line_end=12, lang="python", score_type="keyword", score=1.0,
        )]

    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(retriever, "dense_search", fake_dense)
    monkeypatch.setattr(retriever, "keyword_search", fake_keyword)
    hits = await retriever.retrieve(
        "handler", top_k=5, repo_ids=["00000000-0000-0000-0000-000000000001"]
    )
    assert called == {"dense": 0, "keyword": 1}
    assert hits[0].path == "app.py"
    assert hits[0].line_start == 10
    assert hits[0].score_type == "keyword"


@pytest.mark.asyncio
async def test_mode_endpoint_local(monkeypatch):
    from app.api.v1 import status as status_api

    monkeypatch.setattr(settings, "nova_mode", "local")
    info = await status_api.mode()
    assert info.local is True
    assert info.auth == "none"
    assert info.features.host_executor is True
    assert info.features.isolation == "none"
    assert info.features.semantic_search is False
    assert info.features.jobs_concurrency == 1
    assert info.features.registration is False


@pytest.mark.asyncio
async def test_health_local_does_not_report_qdrant_failure(monkeypatch):
    from app.api.v1 import status as status_api

    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(status_api, "_check_postgres", AsyncMock(return_value="ok"))
    monkeypatch.setattr(status_api, "_check_local_llm", AsyncMock(return_value="ok: local user credential"))
    monkeypatch.setattr(status_api, "_check_sandbox", AsyncMock(return_value={"available": True, "isolation": "none"}))
    result = await status_api.health()
    assert result.status == "ok"
    assert result.components["qdrant"] == "disabled: local mode"
    assert result.components["embedding"] == "disabled: local mode"
    assert result.components["sandbox"]["isolation"] == "none"


@pytest.mark.asyncio
async def test_init_all_local_skips_qdrant_and_seeds_local_user(monkeypatch):
    from app.core.security import auth

    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(init_db, "check_connectivity", AsyncMock(return_value={"postgres": "connected"}))
    monkeypatch.setattr(init_db, "init_postgres", AsyncMock(return_value="already_exists"))
    monkeypatch.setattr(
        init_db, "migrate_legacy_repos",
        AsyncMock(side_effect=AssertionError("must not migrate legacy cloud repos")),
    )
    monkeypatch.setattr(
        init_db, "init_qdrant",
        AsyncMock(side_effect=AssertionError("must not init qdrant in local mode")),
    )
    monkeypatch.setattr(auth, "ensure_local_user", AsyncMock(return_value={"username": "local"}))
    result = await init_db.init_all()
    assert result["qdrant"].startswith("skipped")
    assert result["qdrant_payload"].startswith("skipped")
    assert result["storage"] == "skipped: local mode"
    assert result["users"] == "local: local"


class _FakeConn:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self):
        return self

    def execute(self, *args, **kwargs):
        return None

    def fetchone(self):
        return (1,)


@pytest.mark.asyncio
async def test_check_connectivity_skips_qdrant_socket(monkeypatch):
    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(settings, "embeddings_enabled", False)
    monkeypatch.setattr(init_db.psycopg, "connect", lambda *a, **k: _FakeConn())
    monkeypatch.setattr(
        "qdrant_client.QdrantClient",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not construct QdrantClient")),
    )
    status = await init_db.check_connectivity()
    assert status["postgres"] == "connected"
    assert status["qdrant"].startswith("skipped")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && NOVA_TEST_FAST=1 python -m pytest tests/test_local_retrieval.py -q`

Expected: FAIL — `dense_search` 仍连接 Qdrant；`status_api.mode` 不存在。

- [ ] **Step 3: 实现检索降级**

在 `backend/app/core/rag/dense.py` 的 `dense_search` 开头加入：

```python
    if not settings.use_embeddings:
        return []
```

在 `backend/app/core/rag/retriever.py` 中把固定 legs 改为：

```python
    legs: list[tuple[str, object]] = [("keyword", keyword_search)]
    if settings.use_embeddings:
        legs.insert(0, ("dense", dense_search))
```

并在文件顶部加入：

```python
from app.config import settings
```

同一 Step 中，确保本地索引完全不触碰 Qdrant：

在 `backend/app/core/indexing/pipeline.py` 的 `_embed_and_upload` 开头改为：

```python
    if not pending or not settings.use_embeddings:
        return 0
```

在 `_delete_file_data` 中把 Qdrant 删除包在开关内：

```python
    if chunk_ids and settings.use_embeddings:
        try:
            from app.db.qdrant import delete_point_ids
            await delete_point_ids(chunk_ids)
        except Exception as exc:  # noqa: BLE001
            logger.warning("qdrant_file_delete_failed", file_id=file_id, error=str(exc))
```

在 `index_repo` 的 `if force:` 块中，把 `delete_repo_points` 调用包在 `if settings.use_embeddings:` 内；在 `delete_repo` 的 Qdrant 清理块外同样加入 `if settings.use_embeddings:`。

最后修改 `backend/app/db/init_db.py` 的 `check_connectivity`：把函数末尾的 Qdrant 检测段（从 `try:` + `from qdrant_client import QdrantClient` 到该 `except` 结束）替换为：

```python
    if not settings.use_embeddings:
        status["qdrant"] = "skipped: embeddings disabled"
        return status

    try:
        from qdrant_client import QdrantClient
        client = QdrantClient(url=settings.qdrant_url, timeout=5)
        client.get_collections()
        status["qdrant"] = "connected"
    except Exception as exc:  # noqa: BLE001
        status["qdrant"] = f"failed: {exc}"

    return status
```

对应的 `test_check_connectivity_skips_qdrant_socket` 已在 Step 1 的测试文件中写好。

- [ ] **Step 4: 实现 `/status/mode` 与本地 health**

在 `backend/app/models/schemas.py` 的 `HealthOut` 之前加入：

```python
class ModeFeaturesOut(BaseModel):
    host_executor: bool
    isolation: str          # none | container
    sandbox: str            # host | docker
    semantic_search: bool
    jobs_concurrency: int
    registration: bool


class ModeOut(BaseModel):
    mode: str               # server | local
    local: bool
    auth: str               # login | none
    features: ModeFeaturesOut
    data_dir: str = ""
```

在 `backend/app/api/v1/status.py` 中加入：

```python
async def _check_local_llm() -> str:
    try:
        from app.db import query

        rows = await asyncio.wait_for(
            query(
                "SELECT 1 FROM user_llm_providers "
                "WHERE user_id = (SELECT id FROM users WHERE username = %s) LIMIT 1",
                (settings.local_user,),
            ),
            timeout=CHECK_TIMEOUT,
        )
    except Exception as exc:  # noqa: BLE001
        return f"failed: {exc}"
    return "ok: local user credential" if rows else "failed: no API key configured"


@router.get("/status/mode", response_model=ModeOut)
async def mode():
    return ModeOut(
        mode=settings.nova_mode,
        local=settings.is_local,
        auth="none" if settings.is_local else "login",
        features=ModeFeaturesOut(
            host_executor=settings.use_host_executor,
            isolation="none" if settings.is_local else "container",
            sandbox="host" if settings.is_local else "docker",
            semantic_search=settings.use_embeddings,
            jobs_concurrency=settings.effective_job_max_concurrency,
            registration=(
                False if settings.is_local
                else settings.registration_mode != "closed"
            ),
        ),
        data_dir=str(settings.data_root) if settings.is_local else "",
    )
```

把 `health()` 改为模式分支：

```python
@router.get("/status/health", response_model=HealthOut)
async def health():
    if settings.is_local:
        postgres, llm = await asyncio.gather(_check_postgres(), _check_local_llm())
        sandbox = await _check_sandbox()
        components = {
            "postgres": postgres,
            "qdrant": "disabled: local mode",
            "llm": llm,
            "model": server_default_model() or settings.zhipu_model,
            "embedding": "disabled: local mode",
            "sandbox": sandbox,
            "git": "ok" if _git_available() else "missing",
            "uptime_s": int(time.time() - _STARTED_AT),
            "env": settings.app_env,
        }
        core_ok = postgres == "ok" and llm.startswith("ok")
        return HealthOut(
            status="ok" if core_ok else "degraded",
            version=VERSION,
            components=components,
        )

    postgres, qdrant = await asyncio.gather(_check_postgres(), _check_qdrant())
    sandbox = await _check_sandbox()
    components = {
        "postgres": postgres,
        "qdrant": qdrant,
        "llm": _check_llm(),
        "model": server_default_model() or settings.zhipu_model,
        "embedding": _check_embedding(),
        "sandbox": sandbox,
        "git": "ok" if _git_available() else "missing",
        "uptime_s": int(time.time() - _STARTED_AT),
        "env": settings.app_env,
    }
    llm_ready = settings.llm_configured or not settings.llm_allow_server_fallback
    core_ok = postgres == "ok" and qdrant == "ok" and llm_ready
    return HealthOut(status="ok" if core_ok else "degraded", version=VERSION, components=components)
```

把 `status.py` 的 schemas import 改为：

```python
from app.models.schemas import HealthOut, MetricsOut, ModeFeaturesOut, ModeOut, UsageOut
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd backend && NOVA_TEST_FAST=1 python -m pytest tests/test_local_retrieval.py tests/test_contract.py -q`

Expected: 契约测试可能先失败，因为新增 `ModeOut`；进入 Step 6 重新生成后通过。

- [ ] **Step 6: 重新生成契约**

```bash
cd backend && python -m scripts.export_openapi
cd ../frontend && npm run contract:generate && npm run contract:check
```

Expected: `wrote .../contracts/openapi.json`；`contract types up to date`；`test_contract.py` PASS。

- [ ] **Step 7: 全量回归与提交**

Run: `cd backend && NOVA_TEST_FAST=1 python -m pytest tests -q && ruff check app tests`

Expected: 全绿。

```bash
git add backend/app/core/rag/dense.py backend/app/core/rag/retriever.py backend/app/models/schemas.py backend/app/api/v1/status.py backend/tests/test_local_retrieval.py contracts/openapi.json frontend/src/lib/api-schema.d.ts
git commit -m "feat: degrade retrieval without Qdrant and expose runtime mode"
```

---

## Task 11: 本地单 worker、维护循环裁剪与索引重试

**Files:**
- Create: `backend/app/core/indexing/retry.py`
- Modify: `backend/app/core/jobs/runner.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_local_jobs.py`

**Interfaces:**
- Consumes: `settings.effective_job_max_concurrency`、`settings.is_local`。
- Produces:
  - `JobRunner._claim_one()` 在 `len(_active) >= effective_job_max_concurrency` 时不再查库。
  - `_maintenance_once() -> dict`：本地只执行 `run_cleanup()` + `retry_pending_indexes()`；云端保持原有 5 个维护步骤。
  - `retry_pending_indexes(stale_seconds=600) -> int`。

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_local_jobs.py`：

```python
from unittest.mock import AsyncMock

import pytest

from app.config import settings
from app.core.jobs import runner as runner_module
from app.core.jobs.runner import JobRunner
from app.core.indexing import retry
from app import main as main_module


@pytest.mark.asyncio
async def test_claim_one_stops_at_local_single_worker(monkeypatch):
    monkeypatch.setattr(settings, "nova_mode", "local")
    runner = JobRunner()
    runner._active = {"job-1": object()}
    called = False

    async def fake_execute(*args, **kwargs):
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(runner_module, "execute", fake_execute)
    assert await runner._claim_one() is None
    assert called is False


@pytest.mark.asyncio
async def test_retry_pending_indexes_enqueues_stale_repos(monkeypatch):
    monkeypatch.setattr(settings, "nova_mode", "local")
    enqueued: list[tuple] = []

    async def fake_query(sql, params):
        return [("repo-1", 1), ("repo-2", 2)]

    async def fake_enqueue(repo_id, **kwargs):
        enqueued.append((repo_id, kwargs))
        return "job"

    monkeypatch.setattr(retry, "query", fake_query)
    monkeypatch.setattr(retry, "enqueue_index", fake_enqueue)
    assert await retry.retry_pending_indexes(stale_seconds=60) == 2
    assert enqueued == [
        ("repo-1", {"user_id": 1}),
        ("repo-2", {"user_id": 2}),
    ]


@pytest.mark.asyncio
async def test_retry_pending_indexes_is_server_noop(monkeypatch):
    monkeypatch.setattr(settings, "nova_mode", "server")
    query = AsyncMock()
    monkeypatch.setattr(retry, "query", query)
    assert await retry.retry_pending_indexes() == 0
    query.assert_not_awaited()


@pytest.mark.asyncio
async def test_local_maintenance_skips_cloud_steps(monkeypatch):
    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr("app.core.memory.cleanup.run_cleanup", AsyncMock(return_value={"facts": 3}))
    monkeypatch.setattr(
        "app.core.indexing.retry.retry_pending_indexes", AsyncMock(return_value=2)
    )
    deploy = AsyncMock()
    guests = AsyncMock()
    debt = AsyncMock()
    lessons = AsyncMock()
    monkeypatch.setattr("app.core.deploy.service.cleanup_expired", deploy)
    monkeypatch.setattr("app.core.account_cleanup.cleanup_expired_guests", guests)
    monkeypatch.setattr("app.core.debt.service.scan_stale_repos", debt)
    monkeypatch.setattr("app.core.reflection.service.extract_lessons", lessons)

    summary = await main_module._maintenance_once()
    assert summary == {"facts": 3, "index_retried": 2}
    deploy.assert_not_awaited()
    guests.assert_not_awaited()
    debt.assert_not_awaited()
    lessons.assert_not_awaited()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && NOVA_TEST_FAST=1 python -m pytest tests/test_local_jobs.py -q`

Expected: FAIL — `_maintenance_once` / `retry_pending_indexes` 不存在。

- [ ] **Step 3: 实现索引重试**

创建 `backend/app/core/indexing/retry.py`：

```python
"""Re-enqueue index work that was lost during an unclean local shutdown."""
from app.config import settings
from app.core.jobs.service import enqueue_index
from app.db import query


async def retry_pending_indexes(stale_seconds: int = 600) -> int:
    if not settings.is_local:
        return 0
    rows = await query(
        """
        SELECT r.id, r.user_id FROM repos r
        WHERE r.status IN ('pending', 'indexing')
          AND r.updated_at < now() - (%s * interval '1 second')
          AND NOT EXISTS (
              SELECT 1 FROM jobs j
              WHERE j.kind = 'index'
                AND j.status IN ('queued', 'running')
                AND j.payload->>'repo_id' = r.id::text
          )
        ORDER BY r.updated_at
        LIMIT 20
        """,
        (stale_seconds,),
    )
    retried = 0
    for repo_id, user_id in rows:
        await enqueue_index(str(repo_id), user_id=user_id)
        retried += 1
    return retried
```

- [ ] **Step 4: 实现全局 worker 上限**

在 `backend/app/core/jobs/runner.py` 的 `_claim_one` 开头加入：

```python
        limit = settings.effective_job_max_concurrency
        if limit > 0 and len(self._active) >= limit:
            return None
```

- [ ] **Step 5: 重构维护循环**

把 `backend/app/main.py` 的 `_cleanup_loop` 替换为：

```python
async def _maintenance_once() -> dict:
    """One maintenance pass. Local mode deliberately keeps the list small."""
    from app.core.memory.cleanup import run_cleanup

    summary = await run_cleanup()
    if settings.is_local:
        from app.core.indexing.retry import retry_pending_indexes

        summary["index_retried"] = await retry_pending_indexes()
        return summary

    try:
        from app.core.deploy.service import cleanup_expired
        summary["previews_expired"] = await cleanup_expired()
    except Exception:
        logger.exception("preview_cleanup_failed")
    try:
        from app.core.account_cleanup import cleanup_expired_guests
        summary["guests_expired"] = await cleanup_expired_guests()
    except Exception:
        logger.exception("guest_cleanup_failed")
    try:
        from app.core.debt.service import scan_stale_repos
        summary["debt_scanned"] = await scan_stale_repos()
    except Exception:
        logger.exception("debt_scan_failed")
    try:
        from app.core.reflection.service import extract_lessons
        summary["lessons_extracted"] = await extract_lessons()
    except Exception:
        logger.exception("reflection_failed")
    return summary


async def _cleanup_loop() -> None:
    """Hourly maintenance: long-term memory + mode-specific cleanup."""
    while True:
        try:
            summary = await _maintenance_once()
            logger.info("cleanup_done", **summary)
        except ImportError:
            pass
        except Exception:
            logger.exception("cleanup_failed")
        await asyncio.sleep(_CLEANUP_INTERVAL_S)
```

- [ ] **Step 6: 运行测试确认通过**

Run: `cd backend && NOVA_TEST_FAST=1 python -m pytest tests/test_local_jobs.py -q`

Expected: PASS，4 passed。

- [ ] **Step 7: 全量回归与提交**

Run: `cd backend && NOVA_TEST_FAST=1 python -m pytest tests -q && ruff check app tests`

Expected: 全绿。

```bash
git add backend/app/core/indexing/retry.py backend/app/core/jobs/runner.py backend/app/main.py backend/tests/test_local_jobs.py
git commit -m "feat: run a single local job worker and prune cloud maintenance"
```

---

## Task 12: 首次启动 API（项目路径 + 加密 Key）

**Files:**
- Create: `backend/app/api/v1/local_setup.py`
- Modify: `backend/app/api/v1/router.py`
- Modify: `backend/app/models/schemas.py`
- Test: `backend/tests/test_local_setup.py`
- Regenerate: `contracts/openapi.json`、`frontend/src/lib/api-schema.d.ts`

**Interfaces:**
- Consumes: Task 6 的 `register_local_project` / `validate_local_project_path`；现有 `async save_user_config(user_id: int, *, provider: str, model: str, base_url: str | None = None, api_key: str | None = None, context_window: int | None = None, reasoning_effort: str | None = None, is_default: bool = False) -> dict`。
- Produces:
  - `GET /api/v1/local/setup` → `LocalSetupStatusOut`。
  - `POST /api/v1/local/setup` body `LocalSetupIn` → `LocalSetupResultOut`。
  - 非本地模式两个端点都返回 404。
  - 响应只含 `has_key: true`，绝不回显 `api_key`。
  - Key 只写入本地内嵌 PG 的 `user_llm_providers.api_key_enc`；Fernet 主密钥位于仓库外的 `%APPDATA%/Nova/nova-config.json`（gitignored 配置模式）。

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_local_setup.py`：

```python
import json
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.config import settings
from app.api.v1 import local_setup
from app.models.schemas import LocalSetupIn


def _repo() -> dict:
    return {
        "id": "00000000-0000-0000-0000-000000000001",
        "name": "demo",
        "source": "local:D:/code/demo",
        "status": "pending",
        "kind": "import",
        "origin": "local",
        "error": None,
        "stats": {},
        "created_at": None,
        "smoke": None,
    }


@pytest.mark.asyncio
async def test_setup_status_unconfigured(monkeypatch):
    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(settings, "nova_data_dir", "D:/Nova")
    query = AsyncMock(side_effect=[[(0,)], []])
    monkeypatch.setattr(local_setup, "query", query)
    status = await local_setup.get_local_setup({"id": 1})
    assert status.configured is False
    assert status.project_count == 0
    assert status.has_llm_key is False


@pytest.mark.asyncio
async def test_setup_status_configured(monkeypatch):
    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(settings, "nova_data_dir", "D:/Nova")
    monkeypatch.setattr(
        local_setup, "query",
        AsyncMock(side_effect=[
            [(2,)],
            [("zhipu", "glm-4.7-flash", "encrypted", True)],
        ]),
    )
    status = await local_setup.get_local_setup({"id": 1})
    assert status.configured is True
    assert status.has_llm_key is True
    assert status.default_provider == "zhipu"
    assert status.default_model == "glm-4.7-flash"


@pytest.mark.asyncio
async def test_post_setup_saves_key_but_never_returns_it(monkeypatch, tmp_path):
    project = tmp_path / "demo"
    project.mkdir()
    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(settings, "nova_data_dir", str(tmp_path / "Nova"))
    save = AsyncMock(return_value={})
    register = AsyncMock(return_value=_repo())
    audit = AsyncMock(return_value=None)
    monkeypatch.setattr(local_setup, "save_user_config", save)
    monkeypatch.setattr(local_setup, "register_local_project", register)
    monkeypatch.setattr(local_setup, "log_audit", audit)
    body = LocalSetupIn(
        project_path=str(project),
        provider="zhipu",
        model="glm-4.7-flash",
        api_key="sk-test-secret-1234",
    )
    result = await local_setup.run_local_setup(body, {"id": 1})
    assert result.ok is True
    assert result.has_key is True
    assert result.repo.origin == "local"
    dumped = json.dumps(result.model_dump(mode="json"), ensure_ascii=False)
    assert "sk-test-secret-1234" not in dumped
    save.assert_awaited_once()
    assert save.await_args.kwargs["api_key"] == "sk-test-secret-1234"
    assert "api_key" not in audit.await_args.kwargs["details"]


@pytest.mark.asyncio
async def test_post_setup_requires_key_on_first_run(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(settings, "nova_data_dir", str(tmp_path / "Nova"))
    monkeypatch.setattr(local_setup, "query", AsyncMock(return_value=[]))
    body = LocalSetupIn(project_path=str(tmp_path), api_key=None)
    with pytest.raises(HTTPException) as exc:
        await local_setup.run_local_setup(body, {"id": 1})
    assert exc.value.status_code == 400
    assert "API Key" in exc.value.detail


@pytest.mark.asyncio
async def test_local_setup_rejects_server_mode(monkeypatch):
    monkeypatch.setattr(settings, "nova_mode", "server")
    with pytest.raises(HTTPException) as exc:
        await local_setup.get_local_setup({"id": 1})
    assert exc.value.status_code == 404
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && NOVA_TEST_FAST=1 python -m pytest tests/test_local_setup.py -q`

Expected: FAIL — `ModuleNotFoundError: app.api.v1.local_setup`。

- [ ] **Step 3: 增加 schema**

在 `backend/app/models/schemas.py` 的 `RepoOut` 之后加入：

```python
class LocalSetupIn(BaseModel):
    project_path: str = Field(min_length=1, max_length=2000)
    project_name: Optional[str] = Field(default=None, max_length=120)
    provider: str = Field(default="zhipu", max_length=32)
    model: str = Field(default="glm-4.7-flash", max_length=120)
    api_key: Optional[str] = Field(default=None, max_length=4000)


class LocalSetupStatusOut(BaseModel):
    configured: bool
    data_dir: str
    project_count: int
    has_llm_key: bool
    default_provider: Optional[str] = None
    default_model: Optional[str] = None


class LocalSetupResultOut(BaseModel):
    ok: bool
    repo: RepoOut
    provider: str
    model: str
    has_key: bool
```

- [ ] **Step 4: 实现 setup API**

创建 `backend/app/api/v1/local_setup.py`：

```python
"""First-run local setup: register a folder and save an encrypted LLM key."""
from fastapi import APIRouter, Depends, HTTPException

from app.config import settings
from app.core.llm.user_settings import save_user_config
from app.core.security.audit import AuditAction, log_audit
from app.core.security.auth import get_current_user
from app.local.projects import register_local_project, validate_local_project_path
from app.db import query
from app.models.schemas import (
    LocalSetupIn,
    LocalSetupResultOut,
    LocalSetupStatusOut,
)

router = APIRouter()


def require_local_mode() -> None:
    if not settings.is_local:
        raise HTTPException(status_code=404, detail="仅本地模式提供首次启动接口")


@router.get("/local/setup", response_model=LocalSetupStatusOut)
async def get_local_setup(user: dict = Depends(get_current_user)):
    require_local_mode()
    repo_rows = await query(
        "SELECT count(*) FROM repos WHERE user_id = %s", (user["id"],)
    )
    cred_rows = await query(
        "SELECT provider, model, api_key_enc, is_default FROM user_llm_providers "
        "WHERE user_id = %s ORDER BY is_default DESC, updated_at DESC",
        (user["id"],),
    )
    project_count = int(repo_rows[0][0] or 0) if repo_rows else 0
    has_key = any(str(row[2] or "") for row in cred_rows)
    default = next((row for row in cred_rows if row[3]), cred_rows[0] if cred_rows else None)
    return LocalSetupStatusOut(
        configured=project_count > 0 and has_key,
        data_dir=str(settings.data_root),
        project_count=project_count,
        has_llm_key=has_key,
        default_provider=default[0] if default else None,
        default_model=default[1] if default else None,
    )


@router.post("/local/setup", response_model=LocalSetupResultOut)
async def run_local_setup(
    body: LocalSetupIn, user: dict = Depends(get_current_user)
):
    require_local_mode()
    if not body.api_key:
        existing = await query(
            "SELECT 1 FROM user_llm_providers "
            "WHERE user_id = %s AND api_key_enc <> '' LIMIT 1",
            (user["id"],),
        )
        if not existing:
            raise HTTPException(status_code=400, detail="首次启动请填写 API Key")
    try:
        validate_local_project_path(body.project_path, settings.data_root)
        await save_user_config(
            user["id"],
            provider=body.provider,
            model=body.model,
            api_key=body.api_key,
            is_default=True,
        )
        repo = await register_local_project(
            user, body.project_path, body.project_name
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await log_audit(
        AuditAction.REPO_IMPORT,
        user_id=str(user["id"]),
        details={"repo_id": repo["id"], "source": "local_setup"},
    )
    return LocalSetupResultOut(
        ok=True,
        repo=repo,
        provider=body.provider,
        model=body.model,
        has_key=True,
    )
```

修改 `backend/app/api/v1/router.py`：

```python
from app.api.v1 import (
    admin, auth, builder, chat, contracts, deploys, files, git_ops, jobs, memory,
    local_exec, local_setup, repos, settings_llm, settings_quota, status, tasks,
)
```

```python
api_router.include_router(local_setup.router, tags=["local"])
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd backend && NOVA_TEST_FAST=1 python -m pytest tests/test_local_setup.py -q`

Expected: PASS，5 passed。

- [ ] **Step 6: 重新生成契约**

```bash
cd backend && python -m scripts.export_openapi
cd ../frontend && npm run contract:generate && npm run contract:check
```

Expected: 契约与类型同步，`contract:check` 退出码 0。

- [ ] **Step 7: 全量回归与提交**

Run: `cd backend && NOVA_TEST_FAST=1 python -m pytest tests -q && ruff check app tests`

Expected: 全绿。

```bash
git add backend/app/api/v1/local_setup.py backend/app/api/v1/router.py backend/app/models/schemas.py backend/tests/test_local_setup.py contracts/openapi.json frontend/src/lib/api-schema.d.ts
git commit -m "feat: add first-run local setup API with encrypted LLM key"
```

---

## Task 13: 前端最小本地模式

前端没有测试框架（`frontend/package.json` 无 vitest/jest），本 Task 不引入新测试栈；门禁是 `tsc -b` + `vite build` + 契约检查。逻辑集中在 store 与两个薄对话框，实际行为在 Task 14 的手动验收中验证。

**Files:**
- Modify: `frontend/src/lib/types.ts`
- Modify: `frontend/src/lib/api.ts`
- Create: `frontend/src/stores/mode.ts`
- Create: `frontend/src/components/LocalSetupDialog.tsx`
- Create: `frontend/src/components/LocalFolderDialog.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/views/SettingsView.tsx`
- Modify: `frontend/src/views/WorkspaceView.tsx`

**Interfaces:**
- Consumes: Task 10 `GET /status/mode`、Task 6 `POST /repos/local`、Task 12 `GET/POST /local/setup`；生成后的 `frontend/src/lib/api-schema.d.ts`。
- Produces: `useMode` store（`mode`、`setup`、`load`、`loadSetup`、`markConfigured`）；首次启动弹窗；本地文件夹入口；本地页脚“本地模式 · 无容器隔离”。

- [ ] **Step 1: 扩展类型**

在 `frontend/src/lib/types.ts` 做以下修改。

`User.role` 改为：

```ts
  role: 'admin' | 'demo' | 'local'
```

`Repo` 增加：

```ts
  origin?: 'upload' | 'git' | 'local'
```

在 `LocalExecStatus` 之后加入：

```ts
export type NovaMode = 'server' | 'local'

export type ModeFeatures = {
  host_executor: boolean
  isolation: 'none' | 'container'
  sandbox: 'host' | 'docker'
  semantic_search: boolean
  jobs_concurrency: number
  registration: boolean
}

export type ModeInfo = {
  mode: NovaMode
  local: boolean
  auth: 'login' | 'none'
  features: ModeFeatures
  data_dir: string
}

export type LocalSetupStatus = {
  configured: boolean
  data_dir: string
  project_count: number
  has_llm_key: boolean
  default_provider?: string | null
  default_model?: string | null
}

export type LocalSetupInput = {
  project_path: string
  project_name?: string | null
  provider?: string
  model?: string
  api_key?: string | null
}

export type LocalSetupResult = {
  ok: boolean
  repo: Repo
  provider: string
  model: string
  has_key: boolean
}
```

- [ ] **Step 2: 扩展 API 客户端**

修改 `frontend/src/lib/api.ts`：

`import type { ... } from './types'` 中补充 `LocalSetupInput, LocalSetupResult, LocalSetupStatus, ModeInfo`。

`status` 对象增加：

```ts
    mode: () => request<ModeInfo>('/status/mode'),
```

`repos` 对象增加：

```ts
    localFolder: (path: string, name?: string) =>
      request<Repo>('/repos/local', json({ path, name })),
```

`local` 对象改为：

```ts
  local: {
    status: () => request<LocalExecStatus>('/local/exec/status'),
    setupStatus: () => request<LocalSetupStatus>('/local/setup'),
    setup: (input: LocalSetupInput) =>
      request<LocalSetupResult>('/local/setup', json(input)),
  },
```

- [ ] **Step 3: 创建模式 store**

创建 `frontend/src/stores/mode.ts`：

```ts
import { create } from 'zustand'
import { api, ApiError } from '../lib/api'
import type { LocalSetupStatus, ModeInfo } from '../lib/types'

type ModeState = {
  mode: ModeInfo | null
  setup: LocalSetupStatus | null
  loading: boolean
  error: string | null
  load: () => Promise<ModeInfo | null>
  loadSetup: () => Promise<LocalSetupStatus | null>
  markConfigured: (status: LocalSetupStatus) => void
}

export const useMode = create<ModeState>((set, get) => ({
  mode: null,
  setup: null,
  loading: false,
  error: null,
  load: async () => {
    try {
      const mode = await api.status.mode()
      set({ mode, error: null })
      return mode
    } catch (err) {
      set({ error: err instanceof ApiError ? err.message : '无法获取运行模式' })
      return null
    }
  },
  loadSetup: async () => {
    if (!get().mode?.local) return null
    set({ loading: true })
    try {
      const setup = await api.local.setupStatus()
      set({ setup, loading: false, error: null })
      return setup
    } catch (err) {
      set({ loading: false, error: err instanceof ApiError ? err.message : '无法读取本地配置状态' })
      return null
    }
  },
  markConfigured: (status) => set({ setup: status }),
}))
```

- [ ] **Step 4: 首次启动对话框**

创建 `frontend/src/components/LocalSetupDialog.tsx`：

```tsx
import { FolderOpen, KeyRound } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api, ApiError } from '../lib/api'
import type { LocalSetupStatus } from '../lib/types'
import { Button, Modal, Spinner } from './common'

export function LocalSetupDialog({
  open,
  status,
  onClose,
  onDone,
}: {
  open: boolean
  status: LocalSetupStatus | null
  onClose: () => void
  onDone: (status: LocalSetupStatus) => void
}) {
  const [path, setPath] = useState('')
  const [provider, setProvider] = useState('zhipu')
  const [model, setModel] = useState('glm-4.7-flash')
  const [apiKey, setApiKey] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    setProvider(status?.default_provider || 'zhipu')
    setModel(status?.default_model || 'glm-4.7-flash')
    setApiKey('')
    setError(null)
  }, [open, status?.default_provider, status?.default_model])

  const submit = async () => {
    if (!path.trim()) {
      setError('请填写项目文件夹的绝对路径')
      return
    }
    if (!status?.has_llm_key && !apiKey.trim()) {
      setError('首次启动请填写 API Key')
      return
    }
    setBusy(true)
    setError(null)
    try {
      const result = await api.local.setup({
        project_path: path.trim(),
        provider: provider.trim() || 'zhipu',
        model: model.trim() || 'glm-4.7-flash',
        api_key: apiKey.trim() || null,
      })
      onDone({
        configured: true,
        data_dir: status?.data_dir ?? '',
        project_count: (status?.project_count ?? 0) + 1,
        has_llm_key: true,
        default_provider: result.provider,
        default_model: result.model,
      })
      setPath('')
      setApiKey('')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '保存失败')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal open={open} onClose={onClose} title="首次启动：连接你的项目与模型">
      <div className="space-y-3">
        <p className="text-[11.5px] leading-relaxed text-dim">
          选择本机上的项目文件夹。Nova 只读取该目录并在本机建立索引，不会复制或上传代码；
          <span className="text-warn"> 本地执行无容器隔离</span>。
        </p>
        {status?.data_dir && (
          <p className="break-all font-mono text-[10.5px] text-dim/70">
            数据目录：{status.data_dir}
          </p>
        )}
        <label className="block space-y-1">
          <span className="text-[11px] text-dim">项目文件夹（绝对路径）</span>
          <input
            value={path}
            onChange={(event) => setPath(event.target.value)}
            placeholder="D:\\code\\my-project"
            className="w-full rounded-lg border border-edge bg-base/60 px-2.5 py-1.5 text-[12px] text-ink outline-none transition-colors focus:border-accent/60"
          />
          <span className="text-[10px] text-dim/60">
            原生文件夹选择器将在后续桌面版提供；当前请粘贴绝对路径。
          </span>
        </label>
        <div className="grid gap-2 sm:grid-cols-2">
          <label className="block space-y-1">
            <span className="text-[11px] text-dim">模型厂商</span>
            <input
              value={provider}
              onChange={(event) => setProvider(event.target.value)}
              placeholder="zhipu"
              className="w-full rounded-lg border border-edge bg-base/60 px-2.5 py-1.5 text-[12px] text-ink outline-none focus:border-accent/60"
            />
          </label>
          <label className="block space-y-1">
            <span className="text-[11px] text-dim">模型</span>
            <input
              value={model}
              onChange={(event) => setModel(event.target.value)}
              placeholder="glm-4.7-flash"
              className="w-full rounded-lg border border-edge bg-base/60 px-2.5 py-1.5 text-[12px] text-ink outline-none focus:border-accent/60"
            />
          </label>
        </div>
        <label className="block space-y-1">
          <span className="flex items-center gap-1 text-[11px] text-dim">
            <KeyRound size={11} /> API Key
          </span>
          <input
            type="password"
            value={apiKey}
            onChange={(event) => setApiKey(event.target.value)}
            placeholder={status?.has_llm_key ? '已保存；留空保持不变' : '首次启动必填'}
            autoComplete="off"
            className="w-full rounded-lg border border-edge bg-base/60 px-2.5 py-1.5 text-[12px] text-ink outline-none focus:border-accent/60"
          />
          <span className="text-[10px] text-dim/60">
            Key 仅加密保存在本机，不会写入日志或返回给前端。
          </span>
        </label>
        {error && <p className="text-[11.5px] text-err">{error}</p>}
        <div className="flex justify-end gap-2 pt-1">
          <Button size="sm" onClick={onClose} disabled={busy}>稍后</Button>
          <Button size="sm" variant="primary" onClick={() => void submit()} disabled={busy}>
            {busy ? <Spinner /> : <FolderOpen size={12} />} 保存并打开项目
          </Button>
        </div>
      </div>
    </Modal>
  )
}
```

- [ ] **Step 5: 本地文件夹对话框**

创建 `frontend/src/components/LocalFolderDialog.tsx`：

```tsx
import { FolderOpen } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api, ApiError } from '../lib/api'
import type { Repo } from '../lib/types'
import { Button, Modal, Spinner } from './common'

export function LocalFolderDialog({
  open,
  onClose,
  onOpened,
}: {
  open: boolean
  onClose: () => void
  onOpened: (repo: Repo) => void
}) {
  const [path, setPath] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (open) {
      setPath('')
      setError(null)
    }
  }, [open])

  const submit = async () => {
    if (!path.trim()) {
      setError('请填写项目文件夹的绝对路径')
      return
    }
    setBusy(true)
    setError(null)
    try {
      const repo = await api.repos.localFolder(path.trim())
      onOpened(repo)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '打开失败')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal open={open} onClose={onClose} title="打开本地文件夹">
      <div className="space-y-3">
        <p className="text-[11.5px] leading-relaxed text-dim">
          输入本机项目目录的绝对路径。Nova 原地读取并建立索引，不复制文件；
          删除项目只取消登记，不会删除磁盘内容。<span className="text-warn">执行无容器隔离。</span>
        </p>
        <label className="block space-y-1">
          <span className="text-[11px] text-dim">绝对路径</span>
          <input
            value={path}
            onChange={(event) => setPath(event.target.value)}
            placeholder="D:\\code\\my-project"
            className="w-full rounded-lg border border-edge bg-base/60 px-2.5 py-1.5 text-[12px] text-ink outline-none transition-colors focus:border-accent/60"
          />
        </label>
        {error && <p className="text-[11.5px] text-err">{error}</p>}
        <div className="flex justify-end gap-2">
          <Button size="sm" onClick={onClose} disabled={busy}>取消</Button>
          <Button size="sm" variant="primary" onClick={() => void submit()} disabled={busy}>
            {busy ? <Spinner /> : <FolderOpen size={12} />} 打开并索引
          </Button>
        </div>
      </div>
    </Modal>
  )
}
```

- [ ] **Step 6: 接入 App**

修改 `frontend/src/App.tsx`。

新增 import：

```tsx
import { LocalSetupDialog } from './components/LocalSetupDialog'
import { useMode } from './stores/mode'
```

在 `App()` 内、`useState` 区域增加：

```tsx
  const {
    mode, setup, load: loadMode, loadSetup, markConfigured,
  } = useMode()
  const [setupOpen, setSetupOpen] = useState(false)
```

在 `void check()` 的 effect 后加入：

```tsx
  useEffect(() => {
    void loadMode()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (!user || !mode?.local) return
    void loadSetup().then((status) => {
      if (status && !status.configured) setSetupOpen(true)
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user, mode?.local])
```

游客横幅条件改为：

```tsx
          {!mode?.local && user.is_guest && !guestBannerHidden && (
```

侧栏角色文案改为：

```tsx
                  : user.role === 'admin' ? '管理员' : user.role === 'local' ? '本地用户' : '普通用户'}
```

本地模式没有登录/退出语义，侧栏的退出登录按钮改为条件渲染：

```tsx
            {!mode?.local && (
              <button
                onClick={() => void logout()}
                className="flex h-7 w-7 items-center justify-center rounded-md text-dim hover:bg-raised hover:text-ink"
                title="退出登录"
              >
                <LogOut size={14} />
              </button>
            )}
```

命令面板中的 `logout` 动作也只在云端模式加入：

```tsx
    if (!mode?.local) {
      items.push({ id: 'logout', label: '退出登录', run: () => void logout() })
    }
```

并把 `actions` 的 `useMemo` 依赖数组补上 `mode?.local`。

页脚沙箱项改为：

```tsx
          <span className="hidden md:inline">
            {mode?.local
              ? '本地模式 · 无容器隔离'
              : `沙箱：${sandbox.available ? '可用' : '不可用'}`}
          </span>
```

在 `</div>`（最外层容器）之前、`<CommandPalette ... />` 之后加入：

```tsx
      {mode?.local && (
        <LocalSetupDialog
          open={setupOpen}
          status={setup}
          onClose={() => setSetupOpen(false)}
          onDone={(status) => {
            markConfigured(status)
            setSetupOpen(false)
            void loadLlm()
            void refreshRepos()
          }}
        />
      )}
```

- [ ] **Step 7: 设置页隐藏账号/用量/管理员**

修改 `frontend/src/views/SettingsView.tsx`：

新增 import：

```tsx
import { useMode } from '../stores/mode'
```

在 `const user = useAuth(...)` 之后加入：

```tsx
  const localMode = useMode((s) => s.mode?.local ?? false)
```

把 `sections` 过滤改为：

```tsx
  const sections = SECTIONS.filter((item) => {
    if (localMode && (item.key === 'usage' || item.key === 'account' || item.key === 'admin')) {
      return false
    }
    return item.key !== 'admin' || user?.role === 'admin'
  })
```

- [ ] **Step 8: 工作区入口**

修改 `frontend/src/views/WorkspaceView.tsx`：

lucide import 增加 `FolderOpen`，并加入：

```tsx
import { LocalFolderDialog } from '../components/LocalFolderDialog'
import { useMode } from '../stores/mode'
```

在组件状态区加入：

```tsx
  const localMode = useMode((s) => s.mode?.local ?? false)
  const [localOpen, setLocalOpen] = useState(false)
```

在侧栏标题右侧按钮组（“新建项目”之前）加入：

```tsx
            {localMode && (
              <Button size="sm" variant="ghost" onClick={() => setLocalOpen(true)}>
                <FolderOpen size={12} /> 本地文件夹
              </Button>
            )}
```

在 `RepoCard` 的 `kind === 'builder'` 徽标旁加入：

```tsx
        {repo.origin === 'local' && <Badge tone="accent">本地</Badge>}
```

删除按钮的 `title` 改为：

```tsx
            title={repo.origin === 'local' ? '取消登记（不会删除磁盘文件）' : '删除仓库'}
```

在 `<ImportDialog ... />` 之后加入：

```tsx
      <LocalFolderDialog
        open={localOpen}
        onClose={() => setLocalOpen(false)}
        onOpened={(repo) => {
          void refresh()
          setSelectedId(repo.id)
          setSelectedPath(null)
          setTab('code')
          setLocalOpen(false)
        }}
      />
```

- [ ] **Step 9: 编译与契约门禁**

```bash
cd frontend
npm run contract:check
npm run build
```

Expected: `contract types up to date`；`tsc -b` 无错误；`vite build` 输出 `built in ...`。

- [ ] **Step 10: 提交**

```bash
git add frontend/src/lib/types.ts frontend/src/lib/api.ts frontend/src/stores/mode.ts frontend/src/components/LocalSetupDialog.tsx frontend/src/components/LocalFolderDialog.tsx frontend/src/App.tsx frontend/src/views/SettingsView.tsx frontend/src/views/WorkspaceView.tsx
git commit -m "feat(ui): add minimal local mode setup and folder entry"
```

---

## Task 14: 文档、验收清单与非目标

**Files:**
- Create: `docs/LOCAL_MODE.md`
- Modify: `README.md`
- Modify: `docs/DEPLOY.md`
- Modify: `backend/.env.example`
- Verify only: `docker-compose.yml`（不得产生 diff）

**Interfaces:**
- Consumes: Task 0–13 的全部行为与命令。
- Produces: 本地模式用户文档、云端“行为不变”声明、可执行的验收清单；不产生新代码路径。

- [ ] **Step 1: 编写本地模式文档**

创建 `docs/LOCAL_MODE.md`：

````markdown
# 本地模式（Windows 11）

本地模式让同一套 Nova 后端在你自己电脑上运行：内嵌 PostgreSQL、固定本地用户、直接打开本地文件夹、无容器 HostExecutor、无 Qdrant 的关键词/符号检索、单 worker 后台任务。

**边界：不上传代码、不发送遥测、不访问 Nova 服务器；唯一允许的外部请求是你配置的 LLM API。**

## 1. 前置条件

- Windows 11（v1 验收平台）
- Python 3.12
- Git（可选；存在时索引会遵循 `.gitignore`，否则回退为目录遍历）
- PostgreSQL：默认使用 `pgserver==0.1.4` wheel（Task 0 已选定 A 路线）：
  - 默认（`pgserver`）：`pip install -r requirements-local.txt`
  - 显式回退（`pg_ctl`）：设置 `LOCAL_PG_BIN_DIR` 指向包含 `initdb.exe` / `pg_ctl.exe` 的 PostgreSQL 16 `bin` 目录，并传 `--pg-backend pg_ctl`
- 一个可用的 LLM API Key（首次启动预选智谱 GLM）

## 2. 安装与启动

```powershell
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
# 本地模式默认后端（Task 0 决定：pgserver）：
pip install -r requirements-local.txt

cd ..\frontend
npm ci
npm run build

cd ..\backend
python nova.py local
```

启动成功后终端会输出一行 JSON：

```json
{"event": "listening", "url": "http://127.0.0.1:54321"}
```

用浏览器打开该 URL。首次启动会弹出向导：填写项目文件夹绝对路径、厂商、模型与 API Key。

可选参数：

```powershell
python nova.py local --port 8000          # 固定端口
python nova.py local --pg-backend pg_ctl  # 强制系统 PostgreSQL 二进制
python nova.py local --config D:\Nova\nova-config.json
```

## 3. 数据目录与密钥

默认配置与数据都在 `%APPDATA%\Nova`：

| 路径 | 内容 |
|---|---|
| `nova-config.json` | `secretKey`（Fernet 主密钥）、`dataDir`、`pgBackend`、`allowInstallDeps` |
| `pgdata/` | 内嵌 PostgreSQL 数据目录 |
| `logs/` | 运行日志（不含 API Key） |
| `tmp/` | run_code / 验证的临时工作区，任务结束清理 |

API Key 只写入 PostgreSQL 的 `user_llm_providers.api_key_enc`（Fernet 加密），接口只返回 `has_key`。
`nova-config.json` 不会被提交（仓库 `.gitignore` 已覆盖误放位置）；不要把它发给别人。

## 4. 安全边界（必读）

- 服务只绑定 `127.0.0.1`，不监听局域网。
- 本地模式没有登录页，也没有容器隔离：命令在项目目录直接执行。
- 四档权限仍然生效：`readonly` 拒绝写入/执行；`ask` 每次弹审批；`auto` / `full` 按现有策略放行。
- HostExecutor 会剥离 `*_API_KEY`、`*_TOKEN`、`*_SECRET` 等敏感环境变量，并把路径限制在项目根目录内。
- `install_deps` 默认禁用；只有把 `%APPDATA%\Nova\nova-config.json` 的 `"allowInstallDeps"` 改为 `true`（或启动前设置 `LOCAL_ALLOW_INSTALL_DEPS=true`），并使用 `full` 权限且批准后才会执行，且安装到项目自己的 `.venv` / `node_modules`。
- 本地检索不启用 Qdrant/embedding，使用关键词 + 符号检索；引用仍是 `文件:行号`，证据校验逻辑不变。

## 5. 退出与残留检查

按 `Ctrl+C` 退出。启动器按 “uvicorn → job runner → PostgreSQL” 顺序收尾。

```powershell
Get-Process postgres -ErrorAction SilentlyContinue
Get-Process python -ErrorAction SilentlyContinue
```

两次都应无输出。若 PostgreSQL 残留，检查 `%APPDATA%\Nova\logs` 和 `pgdata\postgres.log`；下一次启动会识别 stale PID 并清理。

## 6. 故障排查

| 现象 | 处理 |
|---|---|
| `pgserver 未安装` | 安装 `requirements-local.txt`，或改用 `--pg-backend pg_ctl` |
| `找不到 initdb` | 设置 `LOCAL_PG_BIN_DIR` 到 PostgreSQL 16 的 `bin` 目录 |
| 启动即退出，提示 SECRET_KEY | 必须用 `python nova.py local`，不要直接 `uvicorn app.main:app` |
| 首次向导提示没有 API Key | 填写 Key 后重试；已保存过可留空 |
| 搜索只有关键词结果 | 本地模式预期行为；health 会显示 `qdrant: disabled: local mode` |
| 端口冲突 | 不传 `--port` 使用随机端口 |
| 想重置本地数据 | 退出后删除 `%APPDATA%\Nova\pgdata`；**不会**删除你的项目文件 |

## 7. 与云端模式的关系

`NOVA_MODE` 默认 `server`，云端 Docker Compose 部署完全不变。本地模式不修改 `docker-compose.yml`、不安装 Qdrant、不启用 Docker 沙箱、不启用账号体系。
````

- [ ] **Step 2: 更新 README**

在 `README.md` 做三处修改。

1. 标题 `### Docker 安全沙箱（绝不降级）` 改为：

```markdown
### Docker 安全沙箱（云端模式，绝不降级）
```

2. 在 `## 本地执行器（nova agent）` 之前加入：

````markdown
## 本地模式（Windows 11）

同一套后端可用 `NOVA_MODE=local` 在本机运行：内嵌 PostgreSQL、固定本地用户、直接打开本地文件夹、无容器 HostExecutor、无 Qdrant 的关键词检索、单 worker 后台任务。

```powershell
cd frontend && npm ci && npm run build
cd ..\backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python nova.py local
```

首次启动填写项目绝对路径与智谱 API Key；Key 只加密保存在本机。完整步骤、数据目录、安全边界与故障排查见 [docs/LOCAL_MODE.md](docs/LOCAL_MODE.md)。

> 本地模式不上传代码、不发送遥测、不访问 Nova 服务器；命令在项目目录直接执行，**没有容器隔离**，工具结果与页脚会明确标注。
````

3. 在 `## 安全说明` 中，把 `- 代码执行只在锁定沙箱中进行；Docker 不可用时工具不可用，不存在宿主机执行路径` 替换为：

```markdown
- 云端模式：代码执行只在锁定沙箱中进行；Docker 不可用时工具不可用，不存在宿主机执行路径。
- 本地模式（`NOVA_MODE=local`）：命令在项目目录直接执行，**无容器隔离**；通过路径 jail、环境变量剥离、权限模式与审批降低风险，UI 与工具结果会明确标注。
```

- [ ] **Step 3: 更新部署文档**

在 `docs/DEPLOY.md` 的标题之后加入：

```markdown
> 本文只覆盖云端模式（Docker Compose）。本地 Windows 桌面运行时见 [LOCAL_MODE.md](LOCAL_MODE.md)；`docker-compose.yml` 与云端部署流程不因本地模式改变。
```

- [ ] **Step 4: 补充 .env.example**

在 `backend/.env.example` 末尾追加（全部注释，默认不改变云端）：

```bash
# ── Local desktop runtime (leave unset for cloud) ──
# NOVA_MODE=local
# NOVA_DATA_DIR=%APPDATA%/Nova
# LOCAL_PG_BACKEND=pgserver
# LOCAL_PG_BIN_DIR=
# LOCAL_ALLOW_INSTALL_DEPS=false
# EMBEDDINGS_ENABLED=false
# SANDBOX_ENABLED=false
```

- [ ] **Step 5: 自动化门禁**

```bash
cd backend
NOVA_TEST_FAST=1 python -m pytest tests -q
ruff check app tests
python -m scripts.export_openapi --check
cd ../frontend
npm run contract:check
npm run build
cd ..
docker compose config >/dev/null
git diff --exit-code docker-compose.yml
```

Expected:
- pytest：`0 failed`；原有 589 passed / 7 skipped 保持通过，新增测试全部通过或按显式理由 skip。
- ruff：`All checks passed!`
- OpenAPI：无漂移（退出码 0）。
- 前端：`contract types up to date`、`vite build` 成功。
- `docker compose config` 退出码 0；`git diff --exit-code docker-compose.yml` 无输出（退出码 0）。

- [ ] **Step 6: 手动验收（Windows 11 本机，逐条打勾）**

按设计文档 §10“本地模式”原样验收：

- [ ] **断网（除 LLM API）可用；不访问 Nova 服务器。** 用 `python nova.py local` 启动后，在 Windows 防火墙/网络面板断开除 LLM 域名外的出站；完成一次对话与检索。`nova-config.json` 的 `serverUrl` 为空，日志中无 Nova 服务器请求。
- [ ] **打开任意本地 Git 仓库，索引与文件树正常。** 工作区“本地文件夹”输入绝对路径 → 状态从 `pending/indexing` 变 `ready`；文件树可展开；`.gitignore` 中的目录不出现。
- [ ] **对话调用 GLM-4.7-Flash，流式输出与工具调用正常。** 提问“X 在哪实现”，回答带 `文件:行号` 引用；触发一次 `read_file` 或 `search_code` 工具。
- [ ] **`readonly` 拒绝写入/执行；`ask` 弹出审批；批准后命令真实执行。** 切到 `readonly` 让 Agent 修改文件/跑命令 → 被拒；切到 `ask` → 出现审批卡，批准后命令输出真实退出码。
- [ ] **编辑产生 diff，批准后落盘；Git diff/commit 可用。** 让 Agent 修改一个文件 → 查看 diff → 批准 → 文件内容变化；工作区 Git 页签执行 `git diff` / `git commit`。
- [ ] **`/fix` 跑通红绿（以 Python/pytest 仓库为准）。** 在一个含失败 pytest 的本地项目中发起 `/fix`；任务先红后绿，补丁批准后应用。
- [ ] **重启应用后会话、项目、设置、Key 均保留。** `Ctrl+C` 后再次 `python nova.py local`；历史会话、项目列表、默认模型与 `has_key: true` 都在。
- [ ] **退出后 PostgreSQL 与 uvicorn 进程干净停止。** 退出后运行：
  ```powershell
  Get-Process postgres -ErrorAction SilentlyContinue
  Get-Process python -ErrorAction SilentlyContinue
  ```
  均无输出。

云端回归（另起环境，不改本地数据）：

- [ ] `docker compose up -d --build` 后：登录、游客、注册、配额、管理员、Docker 沙箱、Qdrant 检索行为与改造前一致。
- [ ] 现有部署脚本与数据无需迁移即可升级（`AUTO_INIT_DB=true` 自动跑 migration 18）。
- [ ] 契约检查通过，无功能瘦身导致的 404/死链。

工程门禁：

- [ ] `pytest` 全绿；`ruff` 干净；前端 build 与 contract check 通过。
- [ ] 安装包在干净 Windows 环境冒烟通过——**Phase 4 交付，本阶段不验收**。

- [ ] **Step 7: 提交**

```bash
git add docs/LOCAL_MODE.md README.md docs/DEPLOY.md backend/.env.example
git commit -m "docs: document local mode, acceptance checklist and cloud guarantees"
```

---

## CI 与不可用服务的测试策略

- 单元测试默认不依赖 PostgreSQL/Qdrant/Docker：`app.local.pg`、`app.core.exec.host`、`local_setup` 的分析与校验均通过 monkeypatch 假实现覆盖。
- `backend/tests/conftest.py` 已有的 `integration` 自动跳过逻辑保持不变；新增需要真实服务的测试必须：
  - 加 `@pytest.mark.integration`；
  - 用 `pytest.mark.skipif` 并写明理由（例如 `requires a local PostgreSQL started by NOVA_TEST_LOCAL_PG=1`）；
  - 在 CI 默认 `NOVA_TEST_FAST=1` 下显示为 skipped，不判失败。
- 真实本地 PG roundtrip 只在显式 `NOVA_TEST_LOCAL_PG=1` 且平台为 Windows 时运行；其余环境跳过并打印原因。
- 前端没有测试框架，门禁为 `tsc -b` + `vite build` + `contract:check`；不新增 vitest/jest，避免 Phase 2 范围膨胀。
- 契约漂移由 `tests/test_contract.py` 与 `npm run contract:check` 双重拦截。

---

## 验收清单（Definition of Done）

### 本地模式（对应设计 §10）

- [ ] 断网（除 LLM API）可用；不访问 Nova 服务器。
- [ ] 打开任意本地 Git 仓库，索引与文件树正常。
- [ ] 对话调用 GLM-4.7-Flash，流式输出与工具调用正常。
- [ ] `readonly` 拒绝写入/执行；`ask` 弹出审批；批准后命令真实执行。
- [ ] 编辑产生 diff，批准后落盘；Git diff/commit 可用。
- [ ] `/fix` 跑通红绿（以 Python/pytest 仓库为准）。
- [ ] 重启应用后会话、项目、设置、Key 均保留。
- [ ] 退出后 PostgreSQL 与 uvicorn 进程干净停止。

### 云端模式

- [ ] `NOVA_MODE` 未设置时，登录、游客、注册、配额、管理员、Docker 沙箱、Qdrant 检索行为不变。
- [ ] `docker-compose.yml` 无 diff；现有部署脚本与数据无需迁移即可升级。
- [ ] 契约检查通过，无 404/死链。

### 工程

- [ ] `pytest` 全绿；`ruff` 干净；前端 build 与 contract check 通过。
- [ ] 模式分支均有显式测试；新增集成测试在 CI 缺失服务时按显式理由 skip。
- [ ] 文档更新：README、`docs/DEPLOY.md`、`docs/LOCAL_MODE.md`。
- [ ] 安装包/干净机器冒烟属 Phase 4，不在本阶段验收。

---

## 明确非目标

- 不做 Phase 3 的前端 Shell、时间线、工具卡重设计、模式徽标视觉打磨；前端只做 Task 13 的最小接入。
- 不做 Phase 4 的 PyInstaller 打包、Electron、NSIS 安装包、自动更新、托盘/单实例；Task 0 只做可行性 spike。
- 不引入 SQLite、SQLAlchemy、React 19、Pydantic v1；不修改 `docker-compose.yml` 或云端 Dockerfile。
- 不做多用户本地账号、注册、邀请、游客、配额；本地固定单用户。
- 不做本地向量检索或 Qdrant 内嵌；无 Qdrant 时明确降级为关键词 + 符号检索。
- 不实现原生文件夹选择器（Phase 4）；Task 13 使用绝对路径输入。
- 不删除、不移动、不复制用户项目文件；删除本地项目只取消登记。

---

## 风险与未知（先后顺序 = 需要优先验证的顺序）

| # | 风险/未知 | 影响 | 验证与应对 |
|---|---|---|---|
| 1 | `pgserver` 0.1.4 在 Windows 11 / Python 3.12 无可用 wheel，或只暴露 Unix socket | 本地模式无法默认内嵌 PG | Task 0 第一天验证；NO-GO 则切 `pg_ctl` + PostgreSQL 16 二进制，Phase 4 改 bundled runtime |
| 2 | `pgserver` 清理后仍残留 postgres 进程 | 违反“退出后干净停止”验收 | Task 0 检查进程；Task 3 stale PID + tree kill 兜底；仍失败则降级 pg_ctl |
| 3 | PyInstaller 打包 pgserver/tree-sitter 原生依赖失败 | Phase 4 路线不确定 | Task 0 只记录结论，不阻塞 Phase 2；失败走 bundled Python runtime + venv |
| 4 | Windows 进程树取消（`taskkill /T /F`）在 shell 包装下漏杀子进程 | 任务取消/退出残留 | Task 7 真实子进程超时测试 + PID 注册表；Task 14 退出残留检查 |
| 5 | HostExecutor 权限边界被路径/符号链接绕过 | 本地文件风险 | Task 6/7 绝对路径、UNC/设备路径、根目录、符号链接逃逸测试；策略层只读/审批不放开 |
| 6 | 无 Qdrant 时检索质量下降导致工具找不到代码 | 对话体验 | Task 10 关键词 + 符号双路，保留 `文件:行号` 证据形状；Task 14 用真实仓库验收 |
| 7 | GLM 免费额度限流或工具调用不稳定 | 验收对话/`/fix` 失败 | 现有退避与错误提示；验收时准备备用 Key；记录真实连通结果 |
| 8 | 本地 PG 数据目录升级/迁移失败 | 重启丢数据 | Task 3 持久化数据目录 + 现有 versioned migrations；Task 14 重启持久化验收 |
| 9 | 首次启动 Key 泄露到日志/响应 | 安全事故 | Task 12 断言响应与审计不含 Key；Task 2 脱敏视图；全局约束禁止日志输出 Key |
| 10 | 前端无自动化测试，模式判断回归 | 本地 UI 错误入口 | 逻辑集中在 store；`tsc` 严格模式；Task 14 手动走查本地/云端两条流程 |

---

## 执行顺序与提交边界

1. Task 0（spike，独立 docs 提交，go/no-go）。
2. Task 1 → Task 2 → Task 3 → Task 4：配置、本地配置、PG、启动器（每步全量测试绿）。
3. Task 5 → Task 6：本地用户/认证、本地项目（每步全量测试绿）。
4. Task 7 → Task 8 → Task 9：HostExecutor、工具接入、verify/任务（每步全量测试绿）。
5. Task 10 → Task 11：检索降级、jobs/维护（每步全量测试绿）。
6. Task 12：首次启动 API（契约同提交）。
7. Task 13：前端最小接入（build + contract）。
8. Task 14：文档与验收（不改运行时代码）。

每个 Task 的提交必须独立可回滚；`NOVA_MODE=server` 下全部新测试仍应通过（新代码路径默认不启用）。


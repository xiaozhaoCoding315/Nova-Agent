# Phase 2 Runtime Spike Results

- 日期：2026-10-31 ~ 2026-11-01（本地时间）
- Windows / Python / CPU：Windows 11 家庭中文版 10.0.26200（Build 26200，x64）；Python 3.12.6（`C:\Program Files\Python312\python.exe`）；12th Gen Intel(R) Core(TM) i5-12500H
- pgserver 版本与 wheel tag：pgserver 0.1.4，`pgserver-0.1.4-cp312-cp312-win_amd64.whl`（12.8 MB）
- pgserver TCP + psycopg + create database：PASS（证据：
  `HOST_KIND tcp`、`PORT 55094`、`VERSION PostgreSQL 16.2 on x86_64-pc-mingw64`、创建 `nova_probe` 后 `DB_OK 1`；
  另在停止后对同一 data 目录重启，`PERSISTED_DB_OK 1`）
- pgserver cleanup 后无 postgres 进程：PASS（证据：`srv.cleanup()` 后 `tasklist | grep -i postgres` 输出 `no postgres process`；
  重启测试再次 cleanup 后同样无残留。注：`CLEANED True` 表示 data 目录被保留——cleanup 只停服务，符合持久化要求）
- pg_ctl 回退：PASS（证据：官方 `postgresql-16.2-1-windows-x64-binaries.zip`（349,357,062 字节）解压 21,250 项；
  `initdb` exit 0；`pg_ctl -o "-p 55432 -h 127.0.0.1" -w start` exit 0；
  `psql --command="select version();"` 输出 `PostgreSQL 16.2, compiled by Visual C++ build 1937, 64-bit`；
  `pg_ctl -m fast -w stop` exit 0；随后 `tasklist | grep -i postgres` 输出 `no postgres process`。
  异常：Git Bash 下短选项 `-c` 跟在 URI 之后被 psql 忽略（`warning: extra command-line argument "select version();" ignored`），
  改用 `--dbname=... --command=...` 后正常，属于 MSYS 参数解析问题而非 PostgreSQL 问题）
- PyInstaller imports：PASS（证据：`pyinstaller==6.10.0` 构建 `nova-spike.exe` 成功，34,586,175 字节；运行输出
  `imports-ok 0.115.0 3.2.3`）
- PyInstaller + pgserver 启动：PASS（证据：同一 exe 运行输出 `embedded-pg-ok True`，退出码 0；退出后无 postgres/nova-spike 进程）
- tree-sitter 原生扩展：PASS（证据：venv 内 `tree_sitter.Parser` 成功解析 `def nova_spike(): return 42`，
  `ROOT module children 1`；exe 内 `import tree_sitter, tree_sitter_python` 成功（随 exe 打包并加载原生扩展）；
  版本 tree-sitter 0.23.2 / tree-sitter-python 0.23.6）
- 本机未安装/未运行 Qdrant，且不依赖 Qdrant 服务（证据：`tasklist | grep -i qdrant` 无输出；
  `netstat -ano | grep -E ":6333|:6334"` 无输出；Task 10 据此实现无 Qdrant 检索）

## 环境记录（Step 1）

```
python --version        -> Python 3.12.6
py -0p                  -> bash: py: command not found（未安装 py launcher；改用 python -m venv）
systeminfo              -> OS 名称: Microsoft Windows 11 家庭中文版 / OS 版本: 10.0.26200
where.exe git           -> D:\Program Files\Git\mingw64\bin\git.exe
                           D:\Program Files\Git\cmd\git.exe
where.exe pg_ctl        -> pg_ctl not on PATH
```

## 命令与结果（Step 2-6）

### Step 2：仓库外一次性 venv

```
cd "$TEMP"                       # C:\Users\28039\AppData\Local\Temp
python -m venv nova-pg-spike     # py launcher 不可用，使用 python 3.12.6
python -m pip install --upgrade pip
  -> 首次 ReadTimeoutError（files.pythonhosted.org），不影响后续步骤
pip index versions pgserver
  -> pgserver (0.1.4)
     Available versions: 0.1.4, 0.1.3, 0.1.2, 0.1.1, 0.1.0
```

### Step 3：Windows cp312 wheel

```
pip download pgserver==0.1.4 --only-binary=:all: -d "$TEMP/nova-pg-wheels"
  -> Saved pgserver-0.1.4-cp312-cp312-win_amd64.whl (12.8 MB)
     Saved fasteners-0.20-py3-none-any.whl
     Saved platformdirs-4.14.2-py3-none-any.whl
     Saved psutil-7.2.2-cp37-abi3-win_amd64.whl
```

### Step 4：TCP / psycopg / 建库 / 持久化 / 干净停止

```
pip install pgserver==0.1.4 "psycopg[binary]==3.2.3"
  -> 首次 ReadTimeoutError；以 --timeout 120 --retries 10 --find-links "$TEMP/nova-pg-wheels" 重试成功
python "$TEMP/spike_pg.py"
  URI <redacted>@127.0.0.1:55094/postgres
  HOST_KIND tcp
  PORT 55094
  VERSION PostgreSQL 16.2 on x86_64-pc-mingw64, co
  DB_OK 1
  CLEANED True
  EXIT=0
tasklist | grep -i postgres     -> no postgres process
```

持久化补充验证（同一 data 目录重启）：

```
python "$TEMP/spike_pg_restart.py"
  DATA C:\Users\28039\AppData\Local\Temp\nova-pg-4kh5onav\pgdata
  PERSISTED_DB_OK 1
  EXIT=0
tasklist | grep -i postgres     -> no postgres process
```

### Step 5：官方 PostgreSQL 二进制回退（B 路线）

本机无 PostgreSQL：`C:\Program Files\PostgreSQL` 不存在、`psql` 不在 PATH、浅层搜索无 `pg_ctl.exe`。
下载官方 EDB ZIP：`postgresql-16.2-1-windows-x64-binaries.zip`（349,357,062 字节，HTTP 200），
用 Python `zipfile` 解压（GNU tar 不支持 ZIP）到 `%TEMP%\pgsql`，共 21,250 项。

```
"$TEMP/pgsql/bin/initdb.exe" -D "$TEMP/nova-pgctl/pgdata" -U nova \
    --auth=scram-sha-256 --pwfile="$TEMP/pgpass.txt" -E UTF8   -> INITDB_EXIT=0
"$TEMP/pgsql/bin/pg_ctl.exe" -D "$TEMP/nova-pgctl/pgdata" \
    -l "$TEMP/nova-pgctl/postgres.log" -o "-p 55432 -h 127.0.0.1" -w start -> START_EXIT=0
PGPASSWORD=<throwaway> "$TEMP/pgsql/bin/psql.exe" --no-psqlrc --no-align --tuples-only \
    --dbname="postgresql://nova@127.0.0.1:55432/postgres" --command="select version();"
  -> PostgreSQL 16.2, compiled by Visual C++ build 1937, 64-bit
"$TEMP/pgsql/bin/pg_ctl.exe" -D "$TEMP/nova-pgctl/pgdata" -m fast -w stop -> STOP_EXIT=0
tasklist | grep -i postgres     -> no postgres process
```

短选项异常：`psql.exe "postgresql://..." -c "select version();"` 在 Git Bash 下输出
`psql: warning: extra command-line argument "select version();" ignored`（退出码 0、无查询结果）；
改用 `--dbname=... --command=...` 正常。记为本机 shell 参数解析异常，不影响 B 路线结论。

### Step 6：PyInstaller + pgserver + tree-sitter

```
pip install "pyinstaller==6.10.0" "fastapi==0.115.0" \
    "tree-sitter==0.23.2" "tree-sitter-python==0.23.6"   -> 成功
venv 内 tree-sitter 解析 Python 源码    -> ROOT module children 1
pyinstaller --onefile --name nova-spike \
    --collect-all pgserver --collect-all tree_sitter --collect-all tree_sitter_python \
    "$TEMP/spike_main.py"                                -> BUILD_EXIT=0
dist/nova-spike.exe                                      -> 34,586,175 字节
"$TEMP/dist/nova-spike.exe"
  imports-ok 0.115.0 3.2.3
  embedded-pg-ok True
  EXE_EXIT=0
tasklist | grep -iE "postgres|nova-spike"                -> no postgres/nova-spike process
```

## 决策

- `local_pg_backend` 默认值：**pgserver**
- Phase 4 打包：**PyInstaller**
- 是否继续 Phase 2：**GO**（PostgreSQL 本身可在这台目标 Windows 11 机器运行；A、B 两条路线均通过）
- 后续 Task 3 必须采用的路径：A 路线——`LOCAL_PG_BACKEND=pgserver` 为默认；
  新增 `backend/requirements-local.txt` 固定 `pgserver==0.1.4`（云端镜像不读取）；
  `pg_ctl` 保留为显式回退后端，使用官方 PostgreSQL 16 ZIP 二进制（B 路线已验证可行）；
  Phase 4 采用 PyInstaller `--onefile`，并继续 `--collect-all pgserver --collect-all tree_sitter --collect-all tree_sitter_python`。

## 备注/异常

- `py` launcher 不存在，实际使用 `python -m venv`（Python 3.12.6），不影响结论。
- PyPI 下载多次出现 `ReadTimeoutError`，通过 `--timeout`/`--retries`/本地 wheel 缓存重试成功；未降低结论可信度。
- pgserver `cleanup()` 停止服务但保留 data 目录（`CLEANED True`），这是持久化所需行为；进程检查无残留。
- 本机首次 `pg_ctl -w start` 与 `psql --version` 均正常；仅 Git Bash 短选项 `-c` 异常（见 Step 5）。
- 所有实验均在 `%TEMP%` 下的一次性 venv/目录中完成，未修改仓库后端/前端/依赖文件；未使用真实凭据。

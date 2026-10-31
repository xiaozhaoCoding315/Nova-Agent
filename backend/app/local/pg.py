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
import tempfile
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
        return path, self.password or secrets.token_urlsafe(24)

    def _start_pgctl(self) -> PgInfo:
        initdb, pg_ctl = self._pg_bins()
        password_path, password = self._password_file()
        if not (self.data_dir / "PG_VERSION").exists():
            # initdb refuses a non-empty target directory, so the password is
            # passed through a temp file outside the cluster and persisted
            # inside it afterwards (needed for later restarts).
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", delete=False,
                dir=self.data_dir.parent, prefix=".pgpassword-",
            ) as handle:
                handle.write(password)
                init_password_path = Path(handle.name)
            try:
                subprocess.run(
                    [
                        str(initdb), "-D", str(self.data_dir), "-U", "nova",
                        "--auth=scram-sha-256", f"--pwfile={init_password_path}",
                        "-E", "UTF8",
                    ],
                    check=True, capture_output=True, timeout=180,
                )
            finally:
                init_password_path.unlink(missing_ok=True)
            password_path.write_text(password, encoding="utf-8")
            try:
                os.chmod(password_path, 0o600)
            except OSError:
                pass
        port = self.port or free_port()
        logfile = self.data_dir / "postgres.log"
        ctl_log = self.data_dir / "pg_ctl.log"
        # Never use pipes here: on Windows the postgres child inherits
        # pg_ctl's stdout/stderr handles, so capture_output would never see
        # EOF and subprocess.run would hang.
        with open(ctl_log, "a", encoding="utf-8") as handle:
            subprocess.run(
                [
                    str(pg_ctl), "-D", str(self.data_dir), "-l", str(logfile),
                    "-o", f"-p {port} -h 127.0.0.1", "-w", "-t", "60", "start",
                ],
                check=True, stdout=handle, stderr=subprocess.STDOUT, timeout=90,
            )
        user = quote(password, safe="")
        dsn = f"postgresql://nova:{user}@127.0.0.1:{port}/{self.dbname}?connect_timeout=3"
        admin = f"postgresql://nova:{user}@127.0.0.1:{port}/postgres?connect_timeout=3"
        return PgInfo(
            dsn=dsn, admin_dsn=admin, host="127.0.0.1", port=port,
            data_dir=self.data_dir, backend="pg_ctl",
        )

    def _stop_pgctl(self) -> None:
        if not (self.data_dir / "PG_VERSION").exists():
            return
        _, pg_ctl = self._pg_bins()
        ctl_log = self.data_dir / "pg_ctl.log"
        try:
            with open(ctl_log, "a", encoding="utf-8") as handle:
                subprocess.run(
                    [
                        str(pg_ctl), "-D", str(self.data_dir),
                        "-m", "fast", "-w", "-t", "30", "stop",
                    ],
                    check=True, stdout=handle, stderr=subprocess.STDOUT, timeout=45,
                )
        finally:
            pid = _read_pid(self.data_dir)
            if pid and pid_alive(pid):
                _kill_tree_sync(pid)

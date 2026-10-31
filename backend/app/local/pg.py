"""Embedded PostgreSQL lifecycle for local mode.

Backend A (pgserver) is a pip package with bundled binaries. Backend B
(pg_ctl) manages official PostgreSQL binaries and is the packaging fallback.
The launcher uses one of them; both expose the same PgInfo.

Termination is verified from ``postmaster.pid`` instead of trusting the
backend: pgserver 0.1.4's ``PostgresServer._cleanup()`` silently returns when
its ``.handle_pids.json`` still lists a crashed process, so every kill path
here proves the PID and data directory before taskkill and only reports
success once the process is gone.
"""
import json
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

import psycopg
import structlog
from psycopg.conninfo import conninfo_to_dict, make_conninfo

logger = structlog.get_logger()

# How long to wait for a force-killed postmaster to disappear.
_KILL_WAIT_SECONDS = 5.0
_POLL_SECONDS = 0.1
_WINDOWS_KERNEL32 = None


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


def _windows_kernel32():
    global _WINDOWS_KERNEL32
    if _WINDOWS_KERNEL32 is None:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        ]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetExitCodeProcess.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        _WINDOWS_KERNEL32 = kernel32
    return _WINDOWS_KERNEL32


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = _windows_kernel32()
        handle = kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, wintypes.BOOL(False), pid
        )
        if not handle:
            return False
        try:
            code = wintypes.DWORD()
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


def _pid_is_postgres(pid: int) -> bool | None:
    """True/False when known, None when the process image cannot be checked."""
    if os.name == "nt":
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if result.returncode != 0 or not result.stdout.strip():
            return None
        if '"' not in result.stdout:
            # tasklist's "no tasks match" info line, not a process row.
            return False
        return "postgres.exe" in result.stdout.lower()
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "comm="],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return "postgres" in result.stdout.lower()


def _windows_cmdline(pid: int) -> str | None:
    """Read a Windows process command line via wmic or PowerShell CIM."""
    queries = (
        ["wmic", "process", "where", f"processid={pid}",
         "get", "commandline", "/value"],
        [
            "powershell", "-NoProfile", "-NonInteractive", "-Command",
            f'(Get-CimInstance Win32_Process -Filter "ProcessId={pid}").CommandLine',
        ],
    )
    for query in queries:
        try:
            result = subprocess.run(
                query, capture_output=True, text=True, timeout=15,
            )
        except FileNotFoundError:
            continue
        except (OSError, subprocess.TimeoutExpired):
            return None
        if result.returncode != 0:
            continue
        if query[0] == "wmic":
            for line in result.stdout.splitlines():
                if line.lower().startswith("commandline="):
                    value = line.split("=", 1)[1].strip()
                    if value:
                        return value
        else:
            value = result.stdout.strip()
            if value:
                return value
    return None


def _process_cmdline(pid: int) -> str | None:
    """Return the command line of ``pid``, or None when it cannot be read."""
    if os.name == "nt":
        return _windows_cmdline(pid)
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "args="],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def _normalized_path(path: Path | str) -> str:
    text = str(Path(path).expanduser().resolve()).rstrip("\\/")
    return os.path.normcase(text)


def _same_path(left: Path | str, right: Path | str) -> bool:
    left_path, right_path = Path(left), Path(right)
    if left_path == right_path:
        return True
    try:
        return left_path.resolve() == right_path.resolve()
    except OSError:
        return False


def _cmdline_mentions_path(cmdline: str, data_dir: Path) -> bool:
    haystack = os.path.normcase(cmdline)
    raw = str(data_dir).rstrip("\\/")
    candidates = set()
    if raw and os.path.isabs(raw):
        candidates.add(os.path.normcase(raw))
    try:
        candidates.add(_normalized_path(data_dir))
    except OSError:
        pass
    return any(candidate and candidate in haystack for candidate in candidates)


def _pid_matches_data_dir(pid: int, data_dir: Path) -> bool:
    """Prove ``pid`` is the PostgreSQL postmaster serving ``data_dir``.

    Fails closed: when the command line cannot be read the identity is
    unknown and the caller must not kill the process.
    """
    if not pid_alive(pid) or _pid_is_postgres(pid) is not True:
        return False
    _, recorded = _read_pid_file(data_dir)
    if recorded is not None and not _same_path(recorded, data_dir):
        return False
    cmdline = _process_cmdline(pid)
    if cmdline is None:
        return False
    return _cmdline_mentions_path(cmdline, data_dir)


def _kill_tree_sync(pid: int) -> bool:
    """Kill ``pid`` and its children; return whether the command succeeded."""
    if os.name == "nt":
        try:
            result = subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True, timeout=20,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return result.returncode == 0
    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _wait_pid_exit(pid: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not pid_alive(pid):
            return True
        time.sleep(_POLL_SECONDS)
    return not pid_alive(pid)


def _read_pid_file(data_dir: Path) -> tuple[int | None, Path | None]:
    """Parse the PID and recorded data directory from ``postmaster.pid``."""
    try:
        lines = (data_dir / "postmaster.pid").read_text(encoding="utf-8").splitlines()
    except OSError:
        return None, None
    try:
        pid = int(lines[0].strip())
    except (ValueError, IndexError):
        pid = None
    recorded = Path(lines[1].strip()) if len(lines) > 1 and lines[1].strip() else None
    return pid, recorded


def _read_pid(data_dir: Path) -> int | None:
    return _read_pid_file(data_dir)[0]


def _log_tail(path: Path, *, lines: int = 20, max_chars: int = 2000) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "<no log>"
    return _tail_text(text, lines=lines, max_chars=max_chars)


def _tail_text(
    value: bytes | str | None, *, lines: int = 20, max_chars: int = 2000
) -> str:
    if not value:
        return "<no output>"
    text = value.decode("utf-8", "replace") if isinstance(value, bytes) else value
    tail = "\n".join(text.splitlines()[-lines:])
    return tail[-max_chars:] or "<no output>"


def _prune_pgserver_handles(data_dir: Path, *, remove_pid: int | None = None) -> None:
    """Drop dead (and optionally our own) PIDs from pgserver's handle list.

    pgserver only stops the server when ``.handle_pids.json`` is exactly
    ``[os.getpid()]``; a PID left behind by a hard-killed app makes every
    later ``cleanup()`` a silent no-op.
    """
    path = data_dir / ".handle_pids.json"
    if not path.exists():
        return
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise ValueError("handle list is not a list")
    except (OSError, ValueError):
        path.unlink(missing_ok=True)
        return
    remaining = [
        value
        for value in raw
        if isinstance(value, int) and value != remove_pid and pid_alive(value)
    ]
    try:
        if remaining:
            path.write_text(json.dumps(remaining), encoding="utf-8")
        else:
            path.unlink(missing_ok=True)
    except OSError:
        logger.warning("local_pg_handle_prune_failed", path=str(path))


def cleanup_stale(data_dir: Path) -> None:
    """Recover from a hard crash: stop a verified orphan PG, remove stale pid.

    Refuses to kill or unlink when a live PID cannot be proven to be the
    PostgreSQL postmaster for ``data_dir``.
    """
    pid_file = data_dir / "postmaster.pid"
    if not pid_file.exists():
        return
    pid = _read_pid(data_dir)
    if pid is None or not pid_alive(pid):
        pid_file.unlink(missing_ok=True)
        return
    is_postgres = _pid_is_postgres(pid)
    if is_postgres is False:
        pid_file.unlink(missing_ok=True)
        return
    if is_postgres is None:
        raise RuntimeError(
            f"refusing to recover {data_dir}: cannot verify whether live PID "
            f"{pid} is PostgreSQL; stop it manually or remove postmaster.pid "
            "after confirming it is stale"
        )
    if not _pid_matches_data_dir(pid, data_dir):
        raise RuntimeError(
            f"refusing to recover {data_dir}: live PostgreSQL PID {pid} is not "
            "verifiably the postmaster for this data directory; stop it manually "
            "or remove postmaster.pid after confirming it is stale"
        )
    logger.warning("local_pg_orphan_stop", pid=pid)
    _kill_tree_sync(pid)
    if not _wait_pid_exit(pid, _KILL_WAIT_SECONDS):
        raise RuntimeError(
            f"stale PostgreSQL postmaster (PID {pid}) did not exit after kill; "
            f"refusing to remove {pid_file}"
        )
    pid_file.unlink(missing_ok=True)


def _validate_dbname(dbname: str) -> None:
    if (
        not dbname
        or not dbname.isascii()
        or not dbname.replace("_", "").isalnum()
    ):
        raise ValueError(f"unsafe database name: {dbname!r}")


def ensure_database_sync(admin_dsn: str, dbname: str) -> None:
    _validate_dbname(dbname)
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
    # Only the exception type is reported: the message may contain connection
    # details and must never echo the generated password.
    raise RuntimeError(
        f"PostgreSQL did not become ready: {type(last).__name__}"
    ) from None


def pgserver_info(uri: str, dbname: str, data_dir: Path | None = None) -> PgInfo:
    _validate_dbname(dbname)
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
    try:
        dsn = make_conninfo(**common, dbname=dbname)
        admin_dsn = make_conninfo(**common, dbname="postgres")
    except Exception:  # noqa: BLE001
        raise RuntimeError("failed to build PostgreSQL connection string") from None
    return PgInfo(
        dsn=dsn,
        admin_dsn=admin_dsn,
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
        _validate_dbname(dbname)
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
        _prune_pgserver_handles(self.data_dir)
        try:
            info = self._start_backend()
            self._started = True
            _wait_ready(info.admin_dsn, timeout=30)
            ensure_database_sync(info.admin_dsn, self.dbname)
            _wait_ready(info.dsn, timeout=10)
        except Exception:
            # A backend can spawn postmaster and still raise (pgserver does
            # before assigning a handle), so clean up from postmaster.pid even
            # though _stop_backend() has no server object to work with.
            self._started = True
            try:
                self._stop_backend()
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "local_pg_start_cleanup_failed",
                    backend=self.backend,
                    error=type(exc).__name__,
                )
            try:
                self._ensure_postmaster_stopped()
            except Exception as exc:  # noqa: BLE001
                # Keep _started=True so a later stop() retries the cleanup.
                logger.error(
                    "local_pg_start_cleanup_failed",
                    backend=self.backend,
                    error=type(exc).__name__,
                )
            else:
                self._started = False
                self._server = None
                self._info = None
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
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "local_pg_stop_failed",
                backend=self.backend,
                error=type(exc).__name__,
            )
        # Never report success until postmaster.pid shows the server is gone.
        self._ensure_postmaster_stopped()
        self._started = False
        self._server = None
        self._info = None
        logger.info("local_pg_stopped", backend=self.backend)

    def _ensure_postmaster_stopped(self) -> None:
        pid_file = self.data_dir / "postmaster.pid"
        pid = _read_pid(self.data_dir)
        if pid is None:
            if pid_file.exists():
                pid_file.unlink(missing_ok=True)
            return
        if not pid_alive(pid):
            pid_file.unlink(missing_ok=True)
            return
        is_postgres = _pid_is_postgres(pid)
        if is_postgres is False:
            # The PID was recycled by an unrelated process; our postmaster
            # is gone and only its lock file is left behind.
            pid_file.unlink(missing_ok=True)
            return
        if is_postgres is None:
            raise RuntimeError(
                f"cannot verify whether live PID {pid} is PostgreSQL; refusing "
                f"to remove the lock file for {self.data_dir}"
            )
        if not _pid_matches_data_dir(pid, self.data_dir):
            raise RuntimeError(
                f"refusing to kill PID {pid}: it is not verifiably the PostgreSQL "
                f"postmaster for {self.data_dir}"
            )
        _kill_tree_sync(pid)
        if not _wait_pid_exit(pid, _KILL_WAIT_SECONDS):
            raise RuntimeError(
                f"PostgreSQL postmaster (PID {pid}) is still running after kill; "
                "state was kept so stop() can be retried"
            )
        pid_file.unlink(missing_ok=True)

    def _start_backend(self) -> PgInfo:
        if self.backend == "pgserver":
            return self._start_pgserver()
        return self._start_pgctl()

    def _stop_backend(self) -> None:
        if self.backend == "pgserver":
            self._stop_pgserver()
            return
        self._stop_pgctl()

    def _stop_pgserver(self) -> None:
        try:
            if self._server is not None:
                self._server.cleanup()
        finally:
            # pgserver keeps our PID in .handle_pids.json even when cleanup()
            # bailed out, which would break the next same-process stop.
            _prune_pgserver_handles(self.data_dir, remove_pid=os.getpid())
            self._forget_pgserver_instance()

    def _forget_pgserver_instance(self) -> None:
        self._server = None
        try:
            import pgserver
        except ImportError:
            return
        try:
            key = Path(self.data_dir).expanduser().resolve()
        except OSError:
            return
        registry = getattr(pgserver.PostgresServer, "_instances", None)
        if isinstance(registry, dict):
            registry.pop(key, None)

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
            except subprocess.CalledProcessError as exc:
                raise RuntimeError(
                    "initdb failed (exit "
                    f"{exc.returncode}): {_tail_text(exc.stderr)}"
                ) from exc
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError("initdb timed out") from exc
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
        try:
            with open(ctl_log, "a", encoding="utf-8") as handle:
                subprocess.run(
                    [
                        str(pg_ctl), "-D", str(self.data_dir), "-l", str(logfile),
                        "-o", f"-p {port} -h 127.0.0.1", "-w", "-t", "60", "start",
                    ],
                    check=True, stdout=handle, stderr=subprocess.STDOUT, timeout=90,
                )
        except (OSError, subprocess.SubprocessError) as exc:
            tail = _log_tail(ctl_log)
            logger.error(
                "local_pg_start_command_failed",
                backend="pg_ctl",
                error=type(exc).__name__,
                log_tail=tail,
            )
            raise RuntimeError(
                f"pg_ctl start failed ({type(exc).__name__}): {tail}"
            ) from exc
        common = {
            "host": "127.0.0.1",
            "port": port,
            "user": "nova",
            "password": password,
            "connect_timeout": 3,
        }
        try:
            dsn = make_conninfo(**common, dbname=self.dbname)
            admin_dsn = make_conninfo(**common, dbname="postgres")
        except Exception:  # noqa: BLE001
            raise RuntimeError(
                "failed to build PostgreSQL connection string"
            ) from None
        return PgInfo(
            dsn=dsn, admin_dsn=admin_dsn, host="127.0.0.1", port=port,
            data_dir=self.data_dir, backend="pg_ctl",
        )

    def _stop_pgctl(self) -> None:
        if not (self.data_dir / "PG_VERSION").exists():
            return
        ctl_log = self.data_dir / "pg_ctl.log"
        try:
            _, pg_ctl = self._pg_bins()
            with open(ctl_log, "a", encoding="utf-8") as handle:
                subprocess.run(
                    [
                        str(pg_ctl), "-D", str(self.data_dir),
                        "-m", "fast", "-w", "-t", "30", "stop",
                    ],
                    check=True, stdout=handle, stderr=subprocess.STDOUT, timeout=45,
                )
        except (OSError, subprocess.SubprocessError) as exc:
            tail = _log_tail(ctl_log)
            logger.error(
                "local_pg_stop_command_failed",
                backend="pg_ctl",
                error=type(exc).__name__,
                log_tail=tail,
            )
            raise RuntimeError(
                f"pg_ctl stop failed ({type(exc).__name__}): {tail}"
            ) from exc

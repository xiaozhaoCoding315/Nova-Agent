"""Configure logging, start PostgreSQL, inject its DSN, then run uvicorn.

Logging is configured before PostgreSQL starts (Task 4 requirement), which
imports the Settings singleton early, so the embedded DSN is also written to
that singleton after startup rather than relying on the environment alone.

Task 3 established that pgserver 0.1.4 cannot restart a cluster after an
unclean shutdown on Windows (its hard-coded 10 s ``pg_ctl`` timeout is
shorter than PostgreSQL's ~30 s log-sharing retry), while the ``pg_ctl``
backend recovers in ~35 s. The launcher therefore retries a failed pgserver
start once with ``pg_ctl`` on the same data dir. The reverse direction is
never attempted: pg_ctl clusters use scram auth and user ``nova`` while
pgserver clusters use trust auth and user ``postgres``, so pg_ctl ->
pgserver cannot work. A failed start never deletes the data directory.

The launcher holds an OS-level instance lock for the whole process lifetime:
a second launch must fail before ``LocalPostgres.start()`` gets a chance to
run stale-server cleanup against the first instance's postmaster.
"""
import json
import os
from pathlib import Path

import structlog

from app.local.config import runtime_env
from app.local.pg import LocalPostgres, free_port

logger = structlog.get_logger()

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
LOCK_NAME = ".nova-instance.lock"


def _load_app():
    from app.main import app

    return app


def _uvicorn_server(app, host: str, port: int):
    import uvicorn

    return uvicorn.Server(
        uvicorn.Config(app, host=host, port=port, log_level="info", access_log=False)
    )


def _configure_logging() -> None:
    """Configure logging before PostgreSQL starts.

    Task 3 removed every traceback/DSN logging path, but the default
    structlog renderer prints whatever a PG error path passes as keywords.
    Configuring first gives that contract a second layer of defense. It is
    skipped when structlog is already configured (e.g. an embedding host).
    """
    if structlog.is_configured():
        return
    from app.core.logging_setup import setup_logging

    setup_logging()


class InstanceLock:
    """Exclusive OS-level lock guarding one local Nova instance.

    The lock file lives next to ``pgdata`` (in ``NOVA_DATA_DIR``), not inside
    it: ``initdb`` refuses a non-empty target directory, so a file placed in
    ``pgdata`` would break the very first start. The OS releases the lock
    when the process exits; ``release()`` exists so ``run()`` can prove it
    released the lock on every exit path.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._handle = None

    @classmethod
    def for_data_dir(cls, data_dir: Path) -> "InstanceLock":
        return cls(Path(data_dir).parent / LOCK_NAME)

    def acquire(self) -> None:
        if self._handle is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self.path, "a+b")  # noqa: SIM115 - held for process lifetime
        try:
            self._lock(handle)
        except OSError:
            handle.close()
            raise RuntimeError(
                f"another Nova Agent instance is already running for "
                f"{self.path.parent} (lock file: {self.path}); refusing to "
                "start a second PostgreSQL"
            ) from None
        self._handle = handle

    @staticmethod
    def _lock(handle) -> None:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            if not handle.read(1):
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def release(self) -> None:
        handle, self._handle = self._handle, None
        if handle is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            handle.close()


def _bundled_pgserver_bin_dir() -> Path | None:
    """PostgreSQL binaries shipped inside the installed pgserver wheel."""
    try:
        import pgserver
    except ImportError:
        return None
    bin_dir = Path(pgserver.__file__).parent / "pginstall" / "bin"
    return bin_dir if bin_dir.is_dir() else None


def _pg_binaries_present(bin_dir: Path) -> bool:
    suffix = ".exe" if os.name == "nt" else ""
    return all(
        (bin_dir / f"{name}{suffix}").is_file() for name in ("pg_ctl", "initdb")
    )


def _resolve_pgctl_bin_dir(env: dict) -> str | None:
    """Resolve the pg_ctl binary directory for the automatic fallback.

    Order: configured ``pgBinDir`` / ``LOCAL_PG_BIN_DIR`` (already folded into
    the runtime env by Task 2) when it actually contains the two binaries ->
    binaries bundled with the pgserver package. A configured path without the
    binaries is skipped rather than used, so a stale config cannot turn a
    recoverable failure into a guaranteed one. ``None`` means no fallback is
    possible.
    """
    configured = (env.get("LOCAL_PG_BIN_DIR") or "").strip()
    if configured and _pg_binaries_present(Path(configured)):
        return configured
    bundled = _bundled_pgserver_bin_dir()
    return str(bundled) if bundled is not None else None


def _apply_dsn_override(dsn: str) -> None:
    """Write the DSN to the Settings singleton, not just the environment.

    ``_configure_logging()`` imports ``app.config`` before PostgreSQL starts,
    so the settings object already exists by the time the DSN is known. Any
    later ``import app.config`` returns the same instance.
    """
    from app.config import settings

    settings.postgres_dsn_override = dsn


def _apply_backend_override(backend: str) -> None:
    """Reflect the backend actually serving in the Settings singleton."""
    from app.config import settings

    settings.local_pg_backend = backend


def _stop_quietly(pg, backend: str) -> None:
    """Best-effort stop of a failed instance; log only the exception type.

    Task 3 keeps ``_started=True`` after a failed start so ``stop()`` retries
    its cleanup; dropping the instance instead would lose that contract.
    """
    try:
        pg.stop()
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "local_pg_stop_after_start_failed",
            backend=backend,
            error=type(exc).__name__,
        )


def _startup_error(data_dir: Path, backend: str, *, detail: str) -> RuntimeError:
    return RuntimeError(
        f"本地 PostgreSQL 启动失败（后端 {backend}；{detail}）。\n"
        f"数据目录已保留：{data_dir}\n"
        "修复方式：使用 `--pg-backend pg_ctl` 启动，并确保 `pgBinDir`"
        "（nova-config.json）或环境变量 `LOCAL_PG_BIN_DIR` 指向 PostgreSQL "
        "的 bin 目录后重试；请勿删除数据目录。"
    )


def _start_postgres(config: dict, env: dict, pg_factory) -> tuple[object, object]:
    data_dir = Path(env["LOCAL_PG_DATA_DIR"])
    factory = pg_factory or LocalPostgres
    backend = env["LOCAL_PG_BACKEND"]
    port = int(config.get("pgPort") or 0)
    bin_dir = env.get("LOCAL_PG_BIN_DIR") or None

    pg = factory(data_dir, backend=backend, port=port, bin_dir=bin_dir)
    try:
        return pg, pg.start()
    except Exception as exc:
        # RuntimeError is the contract, but the broader catch also covers
        # pgserver's subprocess.TimeoutExpired on Windows (the exact failure
        # Task 3 documented) and PostgreSQL readiness errors.
        failed = type(exc).__name__
        logger.error(
            "local_pg_start_failed",
            backend=backend,
            data_dir=str(data_dir),
            error=failed,
        )
        _stop_quietly(pg, backend)
        if backend != "pgserver":
            raise _startup_error(
                data_dir, backend, detail=f"启动失败，错误类型 {failed}"
            ) from exc

        fallback_bin = _resolve_pgctl_bin_dir(env)
        if fallback_bin is None:
            raise _startup_error(
                data_dir,
                backend,
                detail=(
                    f"启动失败（{failed}），且无法自动回退 pg_ctl："
                    "未找到 PostgreSQL bin 目录"
                ),
            ) from exc

        logger.warning(
            "local_pg_fallback",
            from_backend="pgserver",
            to_backend="pg_ctl",
            data_dir=str(data_dir),
            bin_dir=fallback_bin,
        )
        fallback = factory(data_dir, backend="pg_ctl", port=port, bin_dir=fallback_bin)
        try:
            info = fallback.start()
        except Exception as fallback_exc:
            _stop_quietly(fallback, "pg_ctl")
            raise _startup_error(
                data_dir,
                "pgserver -> pg_ctl",
                detail=(
                    "pgserver 与 pg_ctl 均启动失败"
                    f"（pgserver={failed}, pg_ctl={type(fallback_exc).__name__}）"
                ),
            ) from fallback_exc
        logger.warning(
            "local_pg_fallback_started", backend="pg_ctl", data_dir=str(data_dir)
        )
        return fallback, info


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
    _configure_logging()

    lock = InstanceLock.for_data_dir(Path(env["LOCAL_PG_DATA_DIR"]))
    lock.acquire()
    try:
        pg, info = _start_postgres(config, env, pg_factory)
        try:
            actual_backend = getattr(info, "backend", env["LOCAL_PG_BACKEND"])
            if actual_backend != env["LOCAL_PG_BACKEND"]:
                env_map["LOCAL_PG_BACKEND"] = actual_backend
                _apply_backend_override(actual_backend)
            env_map["POSTGRES_DSN_OVERRIDE"] = info.dsn
            _apply_dsn_override(info.dsn)
            listen_port = port or free_port()
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
    finally:
        lock.release()
    return 0

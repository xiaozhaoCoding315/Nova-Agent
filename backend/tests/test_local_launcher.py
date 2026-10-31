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


def _config(tmp_path: Path, **overrides) -> dict:
    config = {
        "version": 1, "mode": "local", "dataDir": str(tmp_path),
        "secretKey": "s" * 64, "pgBackend": "pgserver", "allowInstallDeps": False,
    }
    config.update(overrides)
    return config


def _pg_factory(events: list, info: PgInfo, *, failing: tuple[str, ...] = ()):
    """Fake LocalPostgres that records constructor/start/stop calls."""

    class FakePg:
        def __init__(self, data_dir, **kwargs):
            self.backend = str(kwargs.get("backend"))
            self.bin_dir = kwargs.get("bin_dir")
            Path(data_dir).mkdir(parents=True, exist_ok=True)
            events.append(("pg_init", self.backend, Path(data_dir), self.bin_dir))

        def start(self):
            events.append(("pg_start", self.backend))
            if self.backend in failing:
                raise RuntimeError(f"start failed: {self.backend}")
            return info

        def stop(self):
            events.append(("pg_stop", self.backend))

    return FakePg


class _FakeServer:
    def __init__(self, app, host, port):
        self.app = app

    def run(self):
        pass


@pytest.fixture(autouse=True)
def _restore_settings_dsn():
    """run() writes the DSN to the Settings singleton; keep tests isolated."""
    original = settings.postgres_dsn_override
    yield
    settings.postgres_dsn_override = original


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


# ---------- Task 4 additions: fallback, instance lock, logging ----------


def test_run_falls_back_from_pgserver_to_pg_ctl_once(tmp_path):
    events: list[tuple] = []
    environ: dict[str, str] = {}
    factory = _pg_factory(events, _info(tmp_path), failing=("pgserver",))
    config = _config(tmp_path, pgBinDir=str(tmp_path / "pgbin"))

    code = launcher.run(
        config, environ=environ, pg_factory=factory,
        app_factory=lambda: object(), server_factory=_FakeServer,
    )

    assert code == 0
    inits = [event for event in events if event[0] == "pg_init"]
    assert [event[1] for event in inits] == ["pgserver", "pg_ctl"]
    assert inits[1][2] == Path(environ["LOCAL_PG_DATA_DIR"])
    assert inits[1][3] == str(tmp_path / "pgbin")
    assert [event for event in events if event[0] == "pg_stop"] == [
        ("pg_stop", "pg_ctl")
    ]


def test_run_fallback_uses_bundled_pgserver_binaries(tmp_path, monkeypatch):
    events: list[tuple] = []
    bundled = tmp_path / "bundled" / "bin"
    bundled.mkdir(parents=True)
    monkeypatch.setattr(launcher, "_bundled_pgserver_bin_dir", lambda: bundled)
    factory = _pg_factory(events, _info(tmp_path), failing=("pgserver",))

    launcher.run(
        _config(tmp_path), environ={}, pg_factory=factory,
        app_factory=lambda: object(), server_factory=_FakeServer,
    )

    inits = [event for event in events if event[0] == "pg_init"]
    assert inits[1][1] == "pg_ctl"
    assert inits[1][3] == str(bundled)


def test_run_fallback_without_bin_dir_raises_actionable_error(tmp_path, monkeypatch):
    events: list[tuple] = []
    monkeypatch.setattr(launcher, "_bundled_pgserver_bin_dir", lambda: None)
    factory = _pg_factory(events, _info(tmp_path), failing=("pgserver",))

    with pytest.raises(RuntimeError) as excinfo:
        launcher.run(
            _config(tmp_path), environ={}, pg_factory=factory,
            app_factory=lambda: object(), server_factory=_FakeServer,
        )

    message = str(excinfo.value)
    assert str(tmp_path / "pgdata") in message
    assert "--pg-backend pg_ctl" in message
    assert "pgBinDir" in message
    assert "LOCAL_PG_BIN_DIR" in message
    assert "已保留" in message or "preserved" in message
    assert [event[1] for event in events if event[0] == "pg_init"] == ["pgserver"]
    assert (tmp_path / "pgdata").is_dir()
    # The instance lock must be released even though startup raised.
    lock = launcher.InstanceLock(tmp_path / launcher.LOCK_NAME)
    lock.acquire()
    lock.release()


def test_run_never_falls_back_from_pg_ctl_to_pgserver(tmp_path):
    events: list[tuple] = []
    factory = _pg_factory(events, _info(tmp_path), failing=("pg_ctl",))
    config = _config(tmp_path, pgBackend="pg_ctl", pgBinDir=str(tmp_path / "bin"))

    with pytest.raises(RuntimeError) as excinfo:
        launcher.run(
            config, environ={}, pg_factory=factory,
            app_factory=lambda: object(), server_factory=_FakeServer,
        )

    assert [event[1] for event in events if event[0] == "pg_init"] == ["pg_ctl"]
    assert str(tmp_path / "pgdata") in str(excinfo.value)
    assert "已保留" in str(excinfo.value) or "preserved" in str(excinfo.value)


def test_instance_lock_refuses_second_acquire_and_releases(tmp_path):
    lock_path = tmp_path / launcher.LOCK_NAME
    first = launcher.InstanceLock(lock_path)
    first.acquire()
    try:
        second = launcher.InstanceLock(lock_path)
        with pytest.raises(RuntimeError, match="already"):
            second.acquire()
    finally:
        first.release()

    second.acquire()
    second.release()


def test_run_refuses_second_instance_without_starting_pg(tmp_path):
    events: list[tuple] = []
    lock = launcher.InstanceLock(tmp_path / launcher.LOCK_NAME)
    lock.acquire()
    try:
        with pytest.raises(RuntimeError, match="already"):
            launcher.run(
                _config(tmp_path), environ={},
                pg_factory=_pg_factory(events, _info(tmp_path)),
                app_factory=lambda: object(), server_factory=_FakeServer,
            )
        assert events == []
    finally:
        lock.release()


def test_run_applies_dsn_to_settings_singleton(tmp_path):
    info = _info(tmp_path)

    launcher.run(
        _config(tmp_path), environ={},
        pg_factory=_pg_factory([], info),
        app_factory=lambda: object(), server_factory=_FakeServer,
    )

    assert settings.postgres_dsn_override == info.dsn
    assert settings.postgres_dsn == info.dsn


def test_run_releases_instance_lock_after_success(tmp_path):
    events: list[tuple] = []
    launcher.run(
        _config(tmp_path), environ={},
        pg_factory=_pg_factory(events, _info(tmp_path)),
        app_factory=lambda: object(), server_factory=_FakeServer,
    )

    lock = launcher.InstanceLock(tmp_path / launcher.LOCK_NAME)
    lock.acquire()
    lock.release()


def test_logging_is_configured_before_pg_starts(tmp_path, monkeypatch):
    events: list[str] = []
    monkeypatch.setattr(launcher.structlog, "is_configured", lambda: False)
    monkeypatch.setattr(
        "app.core.logging_setup.setup_logging",
        lambda: events.append("logging"),
    )
    factory = _pg_factory(events, _info(tmp_path))

    launcher.run(
        _config(tmp_path), environ={}, pg_factory=factory,
        app_factory=lambda: object(), server_factory=_FakeServer,
    )

    assert events[0] == "logging"


def test_logging_is_not_initialized_twice(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher.structlog, "is_configured", lambda: True)
    monkeypatch.setattr(
        "app.core.logging_setup.setup_logging",
        lambda: pytest.fail("setup_logging must not run when structlog is configured"),
    )

    launcher.run(
        _config(tmp_path), environ={},
        pg_factory=_pg_factory([], _info(tmp_path)),
        app_factory=lambda: object(), server_factory=_FakeServer,
    )


def test_fallback_bin_dir_prefers_configured_path(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "_bundled_pgserver_bin_dir", lambda: tmp_path / "bundled")

    resolved = launcher._resolve_pgctl_bin_dir(
        {"LOCAL_PG_BIN_DIR": str(tmp_path / "custom")}
    )

    assert resolved == str(tmp_path / "custom")


def test_fallback_bin_dir_uses_bundled_pgserver_package(tmp_path, monkeypatch):
    bundled = tmp_path / "bundled"
    monkeypatch.setattr(launcher, "_bundled_pgserver_bin_dir", lambda: bundled)

    assert launcher._resolve_pgctl_bin_dir({"LOCAL_PG_BIN_DIR": ""}) == str(bundled)


def test_fallback_bin_dir_returns_none_without_any_candidate(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "_bundled_pgserver_bin_dir", lambda: None)

    assert launcher._resolve_pgctl_bin_dir({"LOCAL_PG_BIN_DIR": ""}) is None

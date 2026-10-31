import json
import os
import subprocess

import pytest

from app.local import pg as pg_module
from app.local.pg import (
    LocalPostgres,
    PgInfo,
    cleanup_stale,
    ensure_database_sync,
    free_port,
    pgserver_info,
)


def _write_pid_file(path, pid, data_dir):
    path.write_text(
        f"{pid}\n{data_dir}\n1700000000\n55432\n", encoding="utf-8"
    )


def _make_info(data_dir):
    return PgInfo(
        dsn="postgresql://nova:pw@127.0.0.1:55432/nova_agent",
        admin_dsn="postgresql://nova:pw@127.0.0.1:55432/postgres",
        host="127.0.0.1",
        port=55432,
        data_dir=data_dir,
        backend="pgserver",
    )


class _FakePid:
    """A PID that stays alive until its kill is requested."""

    def __init__(self, pid=424242):
        self.pid = pid
        self.alive = True
        self.kills = []

    def alive_fn(self, pid):
        return self.alive and pid == self.pid

    def kill_fn(self, pid):
        self.kills.append(pid)
        if pid == self.pid:
            self.alive = False
        return True


class _NoopServer:
    """Mimics pgserver's cleanup() bailing out on a stale handle file."""

    def cleanup(self):
        pass


def _install_verified_pid(monkeypatch, fake, tmp_path):
    monkeypatch.setattr(pg_module, "pid_alive", fake.alive_fn)
    monkeypatch.setattr(pg_module, "_pid_is_postgres", lambda pid: True)
    monkeypatch.setattr(
        pg_module, "_process_cmdline",
        lambda pid: f'postgres.exe -D "{tmp_path}"',
    )
    monkeypatch.setattr(pg_module, "_kill_tree_sync", fake.kill_fn)


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
    _write_pid_file(pid_file, 424242, tmp_path)
    monkeypatch.setattr(pg_module, "pid_alive", lambda pid: False)
    cleanup_stale(tmp_path)
    assert not pid_file.exists()


def test_cleanup_stale_kills_orphan_postgres(tmp_path, monkeypatch):
    pid_file = tmp_path / "postmaster.pid"
    _write_pid_file(pid_file, 424242, tmp_path)
    fake = _FakePid()
    _install_verified_pid(monkeypatch, fake, tmp_path)
    cleanup_stale(tmp_path)
    assert fake.kills == [424242]
    assert not pid_file.exists()


def test_cleanup_stale_does_not_kill_recycled_pid(tmp_path, monkeypatch):
    pid_file = tmp_path / "postmaster.pid"
    _write_pid_file(pid_file, 424242, tmp_path)
    killed: list[int] = []
    monkeypatch.setattr(pg_module, "pid_alive", lambda pid: True)
    monkeypatch.setattr(pg_module, "_pid_is_postgres", lambda pid: False)
    monkeypatch.setattr(pg_module, "_kill_tree_sync", lambda pid: killed.append(pid))
    cleanup_stale(tmp_path)
    assert killed == []
    assert not pid_file.exists()


def test_cleanup_stale_refuses_unverified_postgres(tmp_path, monkeypatch):
    pid_file = tmp_path / "postmaster.pid"
    _write_pid_file(pid_file, 424242, tmp_path)
    killed: list[int] = []
    monkeypatch.setattr(pg_module, "pid_alive", lambda pid: True)
    monkeypatch.setattr(pg_module, "_pid_is_postgres", lambda pid: True)
    monkeypatch.setattr(pg_module, "_process_cmdline", lambda pid: None)
    monkeypatch.setattr(pg_module, "_kill_tree_sync", lambda pid: killed.append(pid))
    with pytest.raises(RuntimeError, match="refusing to recover"):
        cleanup_stale(tmp_path)
    assert killed == []
    assert pid_file.exists()


def test_cleanup_stale_refuses_unknown_image_check(tmp_path, monkeypatch):
    pid_file = tmp_path / "postmaster.pid"
    _write_pid_file(pid_file, 424242, tmp_path)
    killed: list[int] = []
    monkeypatch.setattr(pg_module, "pid_alive", lambda pid: True)
    monkeypatch.setattr(pg_module, "_pid_is_postgres", lambda pid: None)
    monkeypatch.setattr(pg_module, "_kill_tree_sync", lambda pid: killed.append(pid))
    with pytest.raises(RuntimeError, match="cannot verify"):
        cleanup_stale(tmp_path)
    assert killed == []
    assert pid_file.exists()


def test_cleanup_stale_refuses_other_data_dir(tmp_path, monkeypatch):
    pid_file = tmp_path / "postmaster.pid"
    _write_pid_file(pid_file, 424242, tmp_path / "other-cluster")
    killed: list[int] = []
    monkeypatch.setattr(pg_module, "pid_alive", lambda pid: True)
    monkeypatch.setattr(pg_module, "_pid_is_postgres", lambda pid: True)
    monkeypatch.setattr(
        pg_module, "_process_cmdline",
        lambda pid: f'postgres.exe -D "{tmp_path / "other-cluster"}"',
    )
    monkeypatch.setattr(pg_module, "_kill_tree_sync", lambda pid: killed.append(pid))
    with pytest.raises(RuntimeError, match="refusing to recover"):
        cleanup_stale(tmp_path)
    assert killed == []
    assert pid_file.exists()


def test_start_and_stop_are_idempotent(tmp_path, monkeypatch):
    info = _make_info(tmp_path)
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
    assert local.info is None


def test_restart_same_data_dir_after_stop(tmp_path, monkeypatch):
    info = _make_info(tmp_path)
    calls: list[str] = []
    local = LocalPostgres(tmp_path, backend="pgserver")
    monkeypatch.setattr(
        local, "_start_backend", lambda: calls.append("start") or info
    )
    monkeypatch.setattr(pg_module, "_wait_ready", lambda dsn, timeout=30: None)
    monkeypatch.setattr(pg_module, "ensure_database_sync", lambda dsn, db: None)
    monkeypatch.setattr(local, "_stop_backend", lambda: calls.append("stop"))

    assert local.start() == info
    local.stop()
    assert local.start() == info
    local.stop()
    assert calls == ["start", "stop", "start", "stop"]


def test_stop_kills_postmaster_when_backend_cleanup_is_a_noop(
    tmp_path, monkeypatch
):
    """pgserver 0.1.4's cleanup() no-ops on a stale .handle_pids.json."""
    pid_file = tmp_path / "postmaster.pid"
    _write_pid_file(pid_file, 424242, tmp_path)
    handles = tmp_path / ".handle_pids.json"
    handles.write_text(json.dumps([999999, os.getpid()]), encoding="utf-8")
    fake = _FakePid()
    _install_verified_pid(monkeypatch, fake, tmp_path)

    local = LocalPostgres(tmp_path, backend="pgserver")
    local._started = True
    local._info = _make_info(tmp_path)
    local._server = _NoopServer()

    local.stop()

    assert fake.kills == [424242]
    assert not pid_file.exists()
    assert not handles.exists()
    assert local._started is False
    assert local.info is None


def test_stop_keeps_state_when_postmaster_survives(tmp_path, monkeypatch):
    pid_file = tmp_path / "postmaster.pid"
    _write_pid_file(pid_file, 424242, tmp_path)
    info = _make_info(tmp_path)
    monkeypatch.setattr(pg_module, "_KILL_WAIT_SECONDS", 0)
    monkeypatch.setattr(pg_module, "pid_alive", lambda pid: True)
    monkeypatch.setattr(pg_module, "_pid_is_postgres", lambda pid: True)
    monkeypatch.setattr(
        pg_module, "_process_cmdline",
        lambda pid: f'postgres.exe -D "{tmp_path}"',
    )
    monkeypatch.setattr(pg_module, "_kill_tree_sync", lambda pid: False)

    local = LocalPostgres(tmp_path, backend="pgserver")
    local._started = True
    local._info = info
    local._server = _NoopServer()

    with pytest.raises(RuntimeError, match="still running"):
        local.stop()

    assert local._started is True
    assert local.info == info
    assert pid_file.exists()


def test_stop_refuses_unverified_pid(tmp_path, monkeypatch):
    pid_file = tmp_path / "postmaster.pid"
    _write_pid_file(pid_file, 424242, tmp_path)
    killed: list[int] = []
    monkeypatch.setattr(pg_module, "pid_alive", lambda pid: True)
    monkeypatch.setattr(pg_module, "_pid_is_postgres", lambda pid: True)
    monkeypatch.setattr(pg_module, "_process_cmdline", lambda pid: None)
    monkeypatch.setattr(pg_module, "_kill_tree_sync", lambda pid: killed.append(pid))

    local = LocalPostgres(tmp_path, backend="pgserver")
    local._started = True
    local._info = _make_info(tmp_path)
    local._server = _NoopServer()

    with pytest.raises(RuntimeError, match="refusing to kill"):
        local.stop()

    assert killed == []
    assert local._started is True
    assert pid_file.exists()


def test_stop_refuses_when_process_image_unknown(tmp_path, monkeypatch):
    pid_file = tmp_path / "postmaster.pid"
    _write_pid_file(pid_file, 424242, tmp_path)
    killed: list[int] = []
    monkeypatch.setattr(pg_module, "pid_alive", lambda pid: True)
    monkeypatch.setattr(pg_module, "_pid_is_postgres", lambda pid: None)
    monkeypatch.setattr(pg_module, "_kill_tree_sync", lambda pid: killed.append(pid))

    local = LocalPostgres(tmp_path, backend="pgserver")
    local._started = True
    local._info = _make_info(tmp_path)
    local._server = _NoopServer()

    with pytest.raises(RuntimeError, match="cannot verify"):
        local.stop()

    assert killed == []
    assert local._started is True
    assert pid_file.exists()


def test_start_failure_force_kills_spawned_postmaster(tmp_path, monkeypatch):
    pid_file = tmp_path / "postmaster.pid"
    fake = _FakePid()

    def failing_backend():
        _write_pid_file(pid_file, fake.pid, tmp_path)
        raise RuntimeError("spawn failed after postmaster start")

    local = LocalPostgres(tmp_path, backend="pgserver")
    monkeypatch.setattr(local, "_start_backend", failing_backend)
    monkeypatch.setattr(local, "_stop_backend", lambda: None)
    _install_verified_pid(monkeypatch, fake, tmp_path)

    with pytest.raises(RuntimeError, match="spawn failed"):
        local.start()

    assert fake.kills == [fake.pid]
    assert not pid_file.exists()
    assert local._started is False
    assert local.info is None


def test_start_failure_keeps_state_when_identity_unknown(tmp_path, monkeypatch):
    pid_file = tmp_path / "postmaster.pid"
    fake = _FakePid()
    monkeypatch.setattr(pg_module, "pid_alive", fake.alive_fn)
    monkeypatch.setattr(pg_module, "_pid_is_postgres", lambda pid: True)
    monkeypatch.setattr(pg_module, "_process_cmdline", lambda pid: None)
    monkeypatch.setattr(pg_module, "_kill_tree_sync", fake.kill_fn)

    def failing_backend():
        _write_pid_file(pid_file, fake.pid, tmp_path)
        raise RuntimeError("spawn failed")

    local = LocalPostgres(tmp_path, backend="pgserver")
    monkeypatch.setattr(local, "_start_backend", failing_backend)
    monkeypatch.setattr(local, "_stop_backend", lambda: None)

    with pytest.raises(RuntimeError, match="spawn failed"):
        local.start()

    assert fake.kills == []
    assert local._started is True
    assert local.info is None
    assert pid_file.exists()

    # A later stop() retries the cleanup once identity can be verified.
    monkeypatch.setattr(
        pg_module, "_process_cmdline",
        lambda pid: f'postgres.exe -D "{tmp_path}"',
    )
    local.stop()

    assert fake.kills == [fake.pid]
    assert not pid_file.exists()
    assert local._started is False
    assert local.info is None


def test_prune_pgserver_handles_drops_dead_and_current(tmp_path, monkeypatch):
    handles = tmp_path / ".handle_pids.json"
    handles.write_text(json.dumps([111, os.getpid(), 222]), encoding="utf-8")
    monkeypatch.setattr(pg_module, "pid_alive", lambda pid: pid == 222)

    pg_module._prune_pgserver_handles(tmp_path, remove_pid=os.getpid())

    assert json.loads(handles.read_text(encoding="utf-8")) == [222]


def test_start_prunes_dead_pgserver_handles(tmp_path, monkeypatch):
    handles = tmp_path / ".handle_pids.json"
    handles.write_text("[111]", encoding="utf-8")
    info = _make_info(tmp_path)
    monkeypatch.setattr(pg_module, "pid_alive", lambda pid: False)
    local = LocalPostgres(tmp_path, backend="pgserver")
    monkeypatch.setattr(local, "_start_backend", lambda: info)
    monkeypatch.setattr(pg_module, "_wait_ready", lambda dsn, timeout=30: None)
    monkeypatch.setattr(pg_module, "ensure_database_sync", lambda dsn, db: None)
    monkeypatch.setattr(local, "_stop_backend", lambda: None)

    local.start()

    assert not handles.exists()


@pytest.mark.skipif(
    os.name != "nt", reason="taskkill is Windows-only"
)
def test_kill_tree_sync_reports_taskkill_failure(monkeypatch):
    monkeypatch.setattr(
        pg_module.subprocess, "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 128),
    )
    assert pg_module._kill_tree_sync(1234) is False

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="taskkill", timeout=20)

    monkeypatch.setattr(pg_module.subprocess, "run", timeout)
    assert pg_module._kill_tree_sync(1234) is False


def _record_pgctl_run(calls):
    def fake_run(args, **kwargs):
        calls.append(list(args))
        return subprocess.CompletedProcess(args[0], 0)

    return fake_run


class _RecordingAdminConn:
    """Fake psycopg connection recording statements sent by the bootstrap."""

    def __init__(self, role_exists: bool):
        self.role_exists = role_exists
        self.statements: list[tuple[object, object]] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, statement, params=None):
        self.statements.append((statement, params))
        return self

    def fetchone(self):
        return (1,) if self.role_exists else None


def _foreign_pgserver_dir(tmp_path):
    """A pgserver-style cluster: trust auth, only the postgres superuser."""
    (tmp_path / "PG_VERSION").write_text("16", encoding="utf-8")
    (tmp_path / "pg_hba.conf").write_text(
        "local   all all                trust\n"
        "host    all all 127.0.0.1/32   trust\n"
        "host    all all ::1/128        trust\n",
        encoding="utf-8",
    )


def test_pgctl_dsn_escapes_password(tmp_path, monkeypatch):
    (tmp_path / "PG_VERSION").write_text("16", encoding="utf-8")
    (tmp_path / "pgpassword").write_text("p@ss w/rd", encoding="utf-8")
    local = LocalPostgres(
        tmp_path, backend="pg_ctl", password="p@ss w/rd"
    )
    monkeypatch.setattr(
        local, "_pg_bins", lambda: (tmp_path / "initdb", tmp_path / "pg_ctl")
    )
    monkeypatch.setattr(
        pg_module.subprocess, "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0),
    )
    monkeypatch.setattr(
        pg_module.psycopg, "connect",
        lambda *a, **k: pytest.fail(
            "a cluster with pgpassword must not be bootstrapped"
        ),
    )

    info = local._start_pgctl()

    from psycopg.conninfo import conninfo_to_dict

    assert conninfo_to_dict(info.dsn)["password"] == "p@ss w/rd"
    assert conninfo_to_dict(info.dsn)["dbname"] == "nova_agent"
    assert conninfo_to_dict(info.admin_dsn)["dbname"] == "postgres"


@pytest.mark.parametrize("role_exists", [False, True])
def test_pgctl_bootstraps_role_on_foreign_cluster(
    tmp_path, monkeypatch, role_exists
):
    _foreign_pgserver_dir(tmp_path)
    assert not (tmp_path / "pgpassword").exists()
    events: list[str] = []
    calls: list[list[str]] = []
    conn = _RecordingAdminConn(role_exists)
    connect_calls: list[tuple[str, dict]] = []

    def fake_connect(dsn, **kwargs):
        events.append("admin_connect")
        connect_calls.append((dsn, kwargs))
        return conn

    monkeypatch.setattr(pg_module.psycopg, "connect", fake_connect)
    monkeypatch.setattr(
        pg_module.subprocess, "run",
        _record_pgctl_run(calls),
    )
    local = LocalPostgres(tmp_path, backend="pg_ctl", password="generated-pw")
    monkeypatch.setattr(
        local, "_pg_bins", lambda: (tmp_path / "initdb", tmp_path / "pg_ctl")
    )

    info = local._start_pgctl()

    # pg_ctl started the foreign cluster before the admin connection.
    assert "start" in calls[0]
    assert events == ["admin_connect"]
    dsn, kwargs = connect_calls[0]
    admin = pg_module.conninfo_to_dict(dsn)
    assert admin["user"] == "postgres"
    assert admin["dbname"] == "postgres"
    assert "password" not in admin
    assert kwargs["autocommit"] is True

    select_sql, select_params = conn.statements[0]
    assert "pg_roles" in select_sql
    assert select_params == ("nova",)
    statement = conn.statements[1][0].as_string(None)
    action = "ALTER" if role_exists else "CREATE"
    assert statement.startswith(f'{action} ROLE "nova"')
    assert "LOGIN CREATEDB PASSWORD" in statement
    assert "'generated-pw'" in statement

    assert (tmp_path / "pgpassword").read_text(encoding="utf-8") == "generated-pw"
    local_dsn = pg_module.conninfo_to_dict(info.dsn)
    assert local_dsn["user"] == "nova"
    assert local_dsn["password"] == "generated-pw"
    assert info.backend == "pg_ctl"


def test_pgctl_bootstrap_failure_is_actionable_and_stops_server(
    tmp_path, monkeypatch
):
    _foreign_pgserver_dir(tmp_path)
    calls: list[list[str]] = []

    def failing_connect(dsn, **kwargs):
        raise pg_module.psycopg.OperationalError("trust rejected")

    monkeypatch.setattr(pg_module.psycopg, "connect", failing_connect)
    monkeypatch.setattr(pg_module.subprocess, "run", _record_pgctl_run(calls))
    local = LocalPostgres(tmp_path, backend="pg_ctl", password="super-secret-value")
    monkeypatch.setattr(
        local, "_pg_bins", lambda: (tmp_path / "initdb", tmp_path / "pg_ctl")
    )

    with pytest.raises(RuntimeError) as excinfo:
        local.start()

    message = str(excinfo.value)
    assert str(tmp_path) in message
    assert "postgres" in message
    assert "已保留" in message or "preserved" in message
    assert "super-secret-value" not in message
    assert not (tmp_path / "pgpassword").exists()
    # start() reuses its cleanup path, so pg_ctl stop was invoked.
    assert any(command[-1] == "stop" for command in calls)
    assert local.info is None


def test_database_name_is_validated(tmp_path):
    with pytest.raises(ValueError, match="unsafe database name"):
        LocalPostgres(tmp_path, dbname="nova; drop database postgres")
    with pytest.raises(ValueError, match="unsafe database name"):
        LocalPostgres(tmp_path, dbname="数据库")


def test_ensure_database_rejects_unsafe_name():
    with pytest.raises(ValueError, match="unsafe database name"):
        ensure_database_sync(
            "postgresql://nova:pw@127.0.0.1:55432/postgres",
            "nova; drop database postgres",
        )


def _pgserver_bundle_bin_dir():
    """Path to pg_ctl/initdb shipped inside the installed pgserver wheel."""
    configured = os.getenv("LOCAL_PG_BIN_DIR")
    if configured:
        return configured
    try:
        import pgserver
    except ImportError:
        return None
    candidate = os.path.join(
        os.path.dirname(pgserver.__file__), "pginstall", "bin"
    )
    return candidate if os.path.isdir(candidate) else None


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


@pytest.mark.skipif(
    os.getenv("NOVA_TEST_LOCAL_PG") != "1",
    reason="set NOVA_TEST_LOCAL_PG=1 to run the real pgserver -> pg_ctl "
    "crash-recovery test",
)
def test_pgserver_cluster_recovers_through_pg_ctl(tmp_path):
    """C1: pgserver init -> unclean kill -> pg_ctl fallback -> SELECT 1."""
    import psycopg

    bin_dir = _pgserver_bundle_bin_dir()
    if bin_dir is None:
        pytest.skip("no pg_ctl binaries; set LOCAL_PG_BIN_DIR")

    data_dir = tmp_path / "pgdata"
    first = LocalPostgres(data_dir, backend="pgserver")
    recovered = None
    try:
        first_info = first.start()
        with psycopg.connect(first_info.dsn, connect_timeout=5) as conn:
            assert conn.execute("select 1").fetchone()[0] == 1
        assert not (data_dir / "pgpassword").exists()

        pid = pg_module._read_pid(data_dir)
        assert pid is not None
        # taskkill can exit non-zero when a child backend exits mid-traversal,
        # even though it killed the postmaster; the crash simulation only
        # requires that the postmaster is gone.
        pg_module._kill_tree_sync(pid)
        assert pg_module._wait_pid_exit(pid, 10)
        # Drop the crashed handle so pgserver's atexit cleanup stays inert.
        pg_module._prune_pgserver_handles(data_dir, remove_pid=os.getpid())

        recovered = LocalPostgres(data_dir, backend="pg_ctl", bin_dir=bin_dir)
        info = recovered.start()
        assert info.backend == "pg_ctl"
        with psycopg.connect(info.dsn, connect_timeout=5) as conn:
            assert conn.execute("select 1").fetchone()[0] == 1
        assert (data_dir / "pgpassword").exists()
    finally:
        if recovered is not None:
            recovered.stop()
        else:
            first.stop()

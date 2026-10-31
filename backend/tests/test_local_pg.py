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


def test_pgctl_dsn_escapes_password(tmp_path, monkeypatch):
    (tmp_path / "PG_VERSION").write_text("16", encoding="utf-8")
    local = LocalPostgres(
        tmp_path, backend="pg_ctl", password="p@ss w/rd"
    )
    monkeypatch.setattr(
        local, "_pg_bins", lambda: (tmp_path / "initdb", tmp_path / "pg_ctl")
    )
    monkeypatch.setattr(
        local, "_password_file", lambda: (tmp_path / "pgpassword", "p@ss w/rd")
    )
    monkeypatch.setattr(
        pg_module.subprocess, "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0),
    )

    info = local._start_pgctl()

    from psycopg.conninfo import conninfo_to_dict

    assert conninfo_to_dict(info.dsn)["password"] == "p@ss w/rd"
    assert conninfo_to_dict(info.dsn)["dbname"] == "nova_agent"
    assert conninfo_to_dict(info.admin_dsn)["dbname"] == "postgres"


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

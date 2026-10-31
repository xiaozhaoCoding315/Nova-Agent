import os

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

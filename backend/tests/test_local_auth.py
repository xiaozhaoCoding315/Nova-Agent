"""Local mode: fixed single user, no login boundary, no quota DB reads."""
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


# ---------------------------------------------------------------------------
# ensure_database targets the override DSN's database (Task 1 carry-forward)
# ---------------------------------------------------------------------------

class _FakeCursor:
    def __init__(self, existing: bool):
        self.existing = existing
        self.calls: list[tuple] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.calls.append((sql, params))

    def fetchone(self):
        return (1,) if self.existing else None


class _FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self):
        return self._cursor


def _patch_connect(monkeypatch, *, existing: bool):
    from app.db import init_db

    cursor = _FakeCursor(existing)
    seen: dict = {}

    def fake_connect(dsn, **kwargs):
        seen["dsn"] = dsn
        seen["kwargs"] = kwargs
        return _FakeConnection(cursor)

    monkeypatch.setattr(init_db.psycopg, "connect", fake_connect)
    return init_db, cursor, seen


@pytest.mark.asyncio
async def test_ensure_database_checks_and_creates_override_dbname(monkeypatch):
    monkeypatch.setattr(settings, "postgres_db", "nova_agent")
    monkeypatch.setattr(
        settings,
        "postgres_dsn_override",
        "postgresql://nova:pw@127.0.0.1:55432/nova_local?connect_timeout=3",
    )
    init_db, cursor, seen = _patch_connect(monkeypatch, existing=False)

    assert await init_db.ensure_database() == "created"

    assert cursor.calls[0] == (
        "SELECT 1 FROM pg_database WHERE datname = %s", ("nova_local",),
    )
    assert cursor.calls[1][0] == 'CREATE DATABASE "nova_local"'
    assert seen["kwargs"] == {"autocommit": True}


@pytest.mark.asyncio
async def test_ensure_database_override_existing_skips_create(monkeypatch):
    monkeypatch.setattr(settings, "postgres_db", "nova_agent")
    monkeypatch.setattr(
        settings,
        "postgres_dsn_override",
        "postgresql://nova:pw@127.0.0.1:55432/nova_local?connect_timeout=3",
    )
    init_db, cursor, _ = _patch_connect(monkeypatch, existing=True)

    assert await init_db.ensure_database() == "already_exists"
    assert len(cursor.calls) == 1
    assert cursor.calls[0][1] == ("nova_local",)


@pytest.mark.asyncio
async def test_ensure_database_without_override_uses_postgres_db(monkeypatch):
    monkeypatch.setattr(settings, "postgres_db", "cloud_custom")
    monkeypatch.setattr(settings, "postgres_dsn_override", "")
    init_db, cursor, _ = _patch_connect(monkeypatch, existing=False)

    assert await init_db.ensure_database() == "created"
    assert cursor.calls[0][1] == ("cloud_custom",)
    assert cursor.calls[1][0] == 'CREATE DATABASE "cloud_custom"'

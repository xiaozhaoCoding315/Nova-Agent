"""Account lifecycle: validation, expiry, token version and admin updates."""
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.config import settings
from app.core.security import accounts
from app.core.security.auth import create_token, hash_password


def test_username_and_password_validation():
    assert accounts.validate_username(" nova_user1 ") == "nova_user1"
    for bad in ("ab", "has-dash", "空格", "a" * 33):
        with pytest.raises(ValueError):
            accounts.validate_username(bad)
    with pytest.raises(ValueError):
        accounts.validate_password("short")
    assert accounts.validate_password("long-enough") == "long-enough"


def test_guest_expiry_helpers():
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    past = datetime.now(timezone.utc) - timedelta(minutes=1)
    assert accounts.is_expired({"expires_at": future}) is False
    assert accounts.is_expired({"expires_at": past}) is True
    assert accounts.is_active({"status": "active", "expires_at": None}) is True
    assert accounts.is_active({"status": "disabled", "expires_at": None}) is False


def test_jwt_carries_token_version():
    token = create_token({
        "id": 3, "username": "u", "role": "demo", "token_version": 4,
    })
    payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
    assert payload["ver"] == 4


@pytest.mark.asyncio
async def test_admin_display_name_does_not_revoke_tokens(monkeypatch):
    calls = []

    async def fake_execute(sql, params):
        calls.append((sql, params))
        return [(1, "u", "New", "demo", "active", False, None, 0, None)]

    monkeypatch.setattr(accounts, "execute", fake_execute)
    await accounts.admin_set_user_fields(1, display_name="New")
    assert "token_version = token_version + 1" not in calls[0][0]


@pytest.mark.asyncio
async def test_admin_disable_revokes_tokens(monkeypatch):
    calls = []

    async def fake_execute(sql, params):
        calls.append((sql, params))
        return [(1, "u", "u", "demo", "disabled", False, None, 1, None)]

    monkeypatch.setattr(accounts, "execute", fake_execute)
    user = await accounts.admin_set_user_fields(1, status="disabled")
    assert "token_version = token_version + 1" in calls[0][0]
    assert user["status"] == "disabled"


@pytest.mark.asyncio
async def test_change_password_bumps_version_and_returns_fresh_user(monkeypatch):
    async def fake_query(_sql, _params):
        return [(hash_password("old-password"),)]

    calls = []

    async def fake_execute(sql, params):
        calls.append((sql, params))
        return []

    async def fake_get_user(user_id):
        return {"id": user_id, "token_version": 2}

    monkeypatch.setattr(accounts, "query", fake_query)
    monkeypatch.setattr(accounts, "execute", fake_execute)
    monkeypatch.setattr(accounts, "get_user_by_id", fake_get_user)

    updated = await accounts.change_password(7, "old-password", "new-password")
    assert updated["token_version"] == 2
    assert "token_version = token_version + 1" in calls[0][0]

    with pytest.raises(ValueError):
        await accounts.change_password(7, "wrong", "new-password")


@pytest.mark.asyncio
async def test_guest_user_is_temporary_and_capped(monkeypatch):
    created = {}

    async def fake_create_user(username, password, **kwargs):
        created.update({"username": username, "password": password, **kwargs})
        return {"id": 9, "username": username, "is_guest": True, **kwargs}

    monkeypatch.setattr(accounts, "create_user", fake_create_user)
    user, _password = await accounts.create_guest_user()
    assert user["is_guest"] is True
    assert created["username"].startswith("guest_")
    assert created["expires_at"] > datetime.now(timezone.utc)

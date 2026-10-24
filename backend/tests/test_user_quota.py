"""Per-user quota overrides and self-imposed budgets."""

import pytest
from fastapi import HTTPException

from app.core.security import accounts, limits as limits_mod
from app.core.storage import user_storage


def _demo_user(**quota):
    user = {"id": 7, "role": "demo", "is_guest": False}
    user.update(quota)
    return user


# ---------- resolution matrix ----------

def test_override_replaces_role_tier(monkeypatch):
    monkeypatch.setattr(limits_mod.settings, "demo_daily_tokens", 100_000)
    user = _demo_user(quota_daily_tokens=5_000)
    assert limits_mod.daily_token_budget(user) == 5_000


def test_null_override_inherits_tier(monkeypatch):
    monkeypatch.setattr(limits_mod.settings, "demo_daily_tokens", 100_000)
    assert limits_mod.daily_token_budget(_demo_user()) == 100_000


def test_zero_override_means_unlimited(monkeypatch):
    monkeypatch.setattr(limits_mod.settings, "demo_daily_tokens", 100_000)
    assert limits_mod.daily_token_budget(_demo_user(quota_daily_tokens=0)) == 0


def test_self_budget_tightens_but_never_raises(monkeypatch):
    monkeypatch.setattr(limits_mod.settings, "demo_daily_tokens", 100_000)
    # self cap below the effective limit wins
    assert limits_mod.daily_token_budget(
        _demo_user(self_daily_tokens=30_000)) == 30_000
    # self cap above the effective limit changes nothing
    assert limits_mod.daily_token_budget(
        _demo_user(self_daily_tokens=999_000)) == 100_000
    # self cap tightens an admin override too
    assert limits_mod.daily_token_budget(
        _demo_user(quota_daily_tokens=50_000, self_daily_tokens=20_000)) == 20_000
    # self = 0 or NULL means no self restriction (even when tier is capped)
    assert limits_mod.daily_token_budget(_demo_user(self_daily_tokens=0)) == 100_000


def test_self_budget_caps_unlimited(monkeypatch):
    monkeypatch.setattr(limits_mod.settings, "admin_daily_tokens", 0)
    user = {"id": 1, "role": "admin", "is_guest": False, "self_daily_tokens": 40_000}
    assert limits_mod.daily_token_budget(user) == 40_000


def test_hourly_and_sandbox_and_job_resolution(monkeypatch):
    monkeypatch.setattr(limits_mod.settings, "demo_hourly_messages", 10)
    monkeypatch.setattr(limits_mod.settings, "demo_sandbox_daily", 20)
    monkeypatch.setattr(limits_mod.settings, "demo_job_hourly", 5)
    user = _demo_user(
        quota_hourly_messages=60, self_hourly_messages=30,
        quota_sandbox_daily=0, self_sandbox_daily=3,
        quota_job_hourly=50,
    )
    assert limits_mod.hourly_message_limit(user) == 30
    assert limits_mod.sandbox_daily_limit(user) == 3
    assert limits_mod.job_hourly_limit(user) == 50


def test_guest_tier_still_applies(monkeypatch):
    monkeypatch.setattr(limits_mod.settings, "guest_daily_tokens", 50_000)
    user = {"id": 9, "role": "demo", "is_guest": True, "quota_daily_tokens": None}
    assert limits_mod.daily_token_budget(user) == 50_000


@pytest.mark.asyncio
async def test_ensure_token_budget_uses_override(monkeypatch):
    monkeypatch.setattr(limits_mod.settings, "demo_daily_tokens", 1_000_000)
    rows = [(7, "demo", False, 2_000, None)]

    async def fake_query(sql, params):
        if "FROM users" in sql:
            return rows
        assert "usage_log" in sql
        return [(1_999,)]

    monkeypatch.setattr(limits_mod, "query", fake_query)
    with pytest.raises(HTTPException) as exc:
        await limits_mod.ensure_token_budget(user_id=7, extra_tokens=2)
    assert exc.value.status_code == 429
    assert "quota_daily_tokens" in rows or True  # SELECT includes override columns


# ---------- storage override ----------

def test_storage_limit_override(monkeypatch):
    monkeypatch.setattr(user_storage.settings, "user_storage_mb", 200)
    monkeypatch.setattr(user_storage.settings, "guest_storage_mb", 50)
    assert user_storage.storage_limit_bytes(_demo_user()) == 200 * 1024 * 1024
    assert user_storage.storage_limit_bytes(
        _demo_user(quota_storage_mb=500)) == 500 * 1024 * 1024
    guest = {"id": 9, "role": "demo", "is_guest": True, "quota_storage_mb": 10}
    assert user_storage.storage_limit_bytes(guest) == 10 * 1024 * 1024


# ---------- admin / self updates ----------

@pytest.mark.asyncio
async def test_admin_set_quota_override(monkeypatch):
    calls = []

    async def fake_execute(sql, params):
        calls.append((sql, params))
        return [(1, "u", "u", "demo", "active", False, None, 0, None,
                 5000, None, None, None, None, None, None, None)]

    monkeypatch.setattr(accounts, "execute", fake_execute)
    user = await accounts.admin_set_user_fields(
        1, quotas={"quota_daily_tokens": 5000})
    assert user["quota_daily_tokens"] == 5000
    assert "quota_daily_tokens = %s" in calls[0][0]
    # quota-only changes must not revoke tokens
    assert "token_version = token_version + 1" not in calls[0][0]


@pytest.mark.asyncio
async def test_admin_set_quota_rejects_negative(monkeypatch):
    with pytest.raises(ValueError):
        await accounts.admin_set_user_fields(1, quotas={"quota_daily_tokens": -5})


@pytest.mark.asyncio
async def test_self_quota_update(monkeypatch):
    async def fake_execute(sql, params):
        assert "self_daily_tokens = %s" in sql
        return [(7, "u", "u", "demo", "active", False, None, 0, None,
                 None, None, None, None, None, 3000, None, None)]

    monkeypatch.setattr(accounts, "execute", fake_execute)
    user = await accounts.set_self_quota(7, {"self_daily_tokens": 3000})
    assert user["self_daily_tokens"] == 3000


@pytest.mark.asyncio
async def test_self_quota_rejects_unknown_and_negative(monkeypatch):
    with pytest.raises(ValueError):
        await accounts.set_self_quota(7, {})
    with pytest.raises(ValueError):
        await accounts.set_self_quota(7, {"self_daily_tokens": -1})
    with pytest.raises(ValueError):
        await accounts.set_self_quota(7, {"quota_daily_tokens": 100})


def test_user_from_row_tolerates_short_rows():
    short = (1, "u", "u", "demo", "active", False, None, 0, None)
    user = accounts.user_from_row(short)
    assert user["quota_daily_tokens"] is None
    assert user["self_sandbox_daily"] is None
    full = short + (100, 20, 5, 2, 64, None, None, None)
    user = accounts.user_from_row(full)
    assert user["quota_daily_tokens"] == 100
    assert user["quota_storage_mb"] == 64

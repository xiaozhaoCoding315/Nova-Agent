"""Quota and usage-accounting tests."""
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.core.llm import usage as usage_mod
from app.core.security import limits as limits_mod


@pytest.mark.asyncio
async def test_admin_with_unlimited_budget_skips_db(monkeypatch):
    query = AsyncMock()
    monkeypatch.setattr(limits_mod, "query", query)
    await limits_mod.ensure_token_budget({"id": 1, "role": "admin"})
    query.assert_not_awaited()


@pytest.mark.asyncio
async def test_demo_budget_exhausted_raises(monkeypatch):
    monkeypatch.setattr(limits_mod.settings, "demo_daily_tokens", 100)
    monkeypatch.setattr(limits_mod, "tokens_used_today", AsyncMock(return_value=99))
    with pytest.raises(HTTPException) as exc:
        await limits_mod.ensure_token_budget({"id": 2, "role": "demo"}, extra_tokens=2)
    assert exc.value.status_code == 429


@pytest.mark.asyncio
async def test_job_quota_rate_limits(monkeypatch):
    monkeypatch.setattr(limits_mod.settings, "demo_job_hourly", 1)
    user = {"id": 98765, "role": "demo"}
    limits_mod._buckets.pop("98765:job:test", None)
    limits_mod.check_job_quota(user, "test")
    with pytest.raises(HTTPException) as exc:
        limits_mod.check_job_quota(user, "test")
    assert exc.value.status_code == 429


@pytest.mark.asyncio
async def test_record_usage_writes_source(monkeypatch):
    execute = AsyncMock()
    monkeypatch.setattr(usage_mod, "execute", execute)
    await usage_mod.record_usage(
        1, None,
        {"prompt_tokens": 3, "completion_tokens": 4, "model": "test"},
        tool_calls=2, source="task",
    )
    sql, params = execute.await_args.args
    assert "source" in sql
    assert params == (1, None, "test", 3, 4, 2, "task")

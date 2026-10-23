"""Daily memory summaries and promotion evidence."""
from datetime import date
from unittest.mock import AsyncMock

import pytest

from app.core.memory import daily as daily_mod


@pytest.mark.asyncio
async def test_rollup_day_compresses_enough_messages(monkeypatch):
    messages = [("user", f"消息 {i}") for i in range(10)]
    query = AsyncMock(side_effect=[[], messages])
    execute = AsyncMock()
    llm = AsyncMock(return_value={"summary": "今天完成了接口与测试。"})
    monkeypatch.setattr(daily_mod, "query", query)
    monkeypatch.setattr(daily_mod, "execute", execute)
    monkeypatch.setattr(daily_mod, "llm_json", llm)
    monkeypatch.setattr(daily_mod, "ensure_token_budget", AsyncMock())

    count = await daily_mod.rollup_day(1, date(2026, 10, 22))

    assert count == 10
    llm.assert_awaited_once()
    sql, params = execute.await_args.args
    assert "INSERT INTO memory_daily" in sql
    assert params[0] == 1
    assert params[2] == "今天完成了接口与测试。"


@pytest.mark.asyncio
async def test_rollup_day_skips_small_days(monkeypatch):
    monkeypatch.setattr(
        daily_mod, "query",
        AsyncMock(side_effect=[[], [("user", "短对话")]]),
    )
    llm = AsyncMock()
    monkeypatch.setattr(daily_mod, "llm_json", llm)

    assert await daily_mod.rollup_day(1, date(2026, 10, 22)) == 0
    llm.assert_not_awaited()


def test_daily_summary_truncates_to_40_lines():
    text = "\n".join(f"line {i}" for i in range(60))
    out = daily_mod._truncate(text)
    assert len(out.splitlines()) == 40
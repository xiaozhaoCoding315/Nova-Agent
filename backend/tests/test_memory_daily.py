"""Daily memory summaries and promotion evidence."""
from datetime import date
from unittest.mock import AsyncMock

import pytest

from app.core.memory import daily as daily_mod
from app.core.memory import scope as scope_mod


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


def test_retrospective_questions_are_detected():
    assert daily_mod.is_retrospective("我们昨天做到哪了？")
    assert daily_mod.is_retrospective("上次用的什么方案")
    assert daily_mod.is_retrospective("What did we do last time?")
    assert not daily_mod.is_retrospective("帮我写一个函数")


@pytest.mark.asyncio
async def test_recent_daily_filters_by_scope_and_window(monkeypatch):
    query = AsyncMock(return_value=[
        (date(2026, 11, 21), "完成了检索", "repo", "r1"),
    ])
    monkeypatch.setattr(daily_mod, "query", query)

    rows = await daily_mod.recent_daily(
        7, [scope_mod.Scope("global", ""), scope_mod.Scope("repo", "r1")],
        days=7, limit=5,
    )

    assert rows == [{
        "day": "2026-11-21", "summary": "完成了检索",
        "scope_type": "repo", "scope_id": "r1",
    }]
    sql, params = query.await_args.args
    assert "(scope_type = %s AND scope_id = %s)" in sql
    assert params[0] == 7
    assert params[-1] == 5


def test_daily_block_labels_scope_and_keeps_order():
    block = daily_mod.format_daily_block([
        {"day": "2026-11-21", "summary": "完成检索", "scope_type": "repo", "scope_id": "r1"},
        {"day": "2026-11-20", "summary": "完成迁移", "scope_type": "dev", "scope_id": ""},
    ])

    assert "近期日摘要" in block
    assert "- 2026-11-21 · 仓库: 完成检索" in block
    assert block.index("2026-11-21") < block.index("2026-11-20")
    assert daily_mod.format_daily_block([]) == ""


@pytest.mark.asyncio
async def test_rollup_yesterday_includes_single_repo_scopes(monkeypatch):
    monkeypatch.setattr(daily_mod, "query", AsyncMock(side_effect=[
        [(1, "dev", "")],
        [(1, "r1")],
    ]))
    rollup = AsyncMock(return_value=10)
    monkeypatch.setattr(daily_mod, "rollup_day", rollup)

    written = await daily_mod.rollup_yesterday()

    assert written == 2
    scopes = [(call.kwargs["scope_type"], call.kwargs["scope_id"]) for call in rollup.await_args_list]
    assert ("dev", "") in scopes
    assert ("repo", "r1") in scopes
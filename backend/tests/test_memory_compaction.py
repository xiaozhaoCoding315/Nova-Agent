"""Recoverable in-turn compaction: summarize before truncating, persist, reload."""
from unittest.mock import AsyncMock

import pytest

from app.core.agent import context_governor
from app.core.memory import compaction as compaction_mod


def test_needs_compaction_respects_window():
    small = [{"role": "user", "content": "hi"}]
    huge = [
        {"role": "user", "content": "x" * 20_000},
        {"role": "assistant", "content": "y" * 20_000},
        {"role": "user", "content": "continue"},
    ]

    assert context_governor.needs_compaction(small, window=8_000) is False
    assert context_governor.needs_compaction(huge, window=8_000) is True


@pytest.mark.asyncio
async def test_summarize_for_compaction_uses_utility_model(monkeypatch):
    llm = AsyncMock(return_value={"summary": "目标：修复登录；未完成：补测试"})
    monkeypatch.setattr(compaction_mod, "llm_json", llm)
    monkeypatch.setattr(compaction_mod, "ensure_token_budget", AsyncMock())

    summary = await compaction_mod.summarize_for_compaction(
        7, "s1",
        [
            {"role": "user", "content": "修复登录"},
            {"role": "assistant", "content": "已定位到 session.py"},
            {"role": "tool", "content": "pytest failed"},
        ],
        turn_id="t1",
    )

    assert summary == "目标：修复登录；未完成：补测试"
    prompt = llm.await_args.args[0]
    assert "用户: 修复登录" in prompt
    assert "工具: pytest failed" in prompt


@pytest.mark.asyncio
async def test_record_compaction_persists_turn_and_token_counts(monkeypatch):
    execute = AsyncMock(return_value=[(9,)])
    monkeypatch.setattr(compaction_mod, "execute", execute)

    record_id = await compaction_mod.record_compaction(
        "s1", "摘要", turn_id="t1", message_count=6,
        tokens_before=9000, tokens_after=5000,
    )

    assert record_id == 9
    sql, params = execute.await_args.args
    assert "INSERT INTO compaction_records" in sql
    assert params == ("s1", "t1", "摘要", 6, 9000, 5000)


@pytest.mark.asyncio
async def test_compaction_endpoint_is_owner_scoped(monkeypatch):
    from app.api.v1 import chat

    monkeypatch.setattr(
        chat.session_mod, "get_session", AsyncMock(return_value={"id": "s1"})
    )
    query = AsyncMock(return_value=[(3, "t1", "压缩摘要", 6, 9000, 5000, None)])
    monkeypatch.setattr(chat, "query", query)

    rows = await chat.get_session_compactions("s1", {"id": 7})

    assert rows[0]["summary"] == "压缩摘要"
    assert rows[0]["tokens_before"] == 9000
    sql, params = query.await_args.args
    assert "WHERE session_id = %s" in sql
    assert params == ("s1",)


@pytest.mark.asyncio
async def test_latest_compaction_requires_session_owner(monkeypatch):
    query = AsyncMock(return_value=[("上一轮摘要",)])
    monkeypatch.setattr(compaction_mod, "query", query)

    summary = await compaction_mod.latest_compaction("s1", 7)

    assert summary == "上一轮摘要"
    sql, params = query.await_args.args
    assert "JOIN sessions s ON s.id = c.session_id" in sql
    assert "s.user_id = %s" in sql
    assert params == ("s1", 7)

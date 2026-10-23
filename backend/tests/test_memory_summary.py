"""Rolling session summary: batching, truncation, and prompt injection."""
from unittest.mock import AsyncMock

import pytest

from app.core.memory import session as session_mod
from app.core.memory import summary as summary_mod
from app.core.memory.context import build_system_prompt


def _messages(start: int, count: int) -> list[dict]:
    return [
        {"id": i, "role": "user" if i % 2 else "assistant", "content": f"消息 {i}"}
        for i in range(start, start + count)
    ]


@pytest.mark.asyncio
async def test_summarize_folds_batch_and_keeps_recent(monkeypatch):
    monkeypatch.setattr(
        session_mod, "summary_state", AsyncMock(return_value=("旧摘要", 10))
    )
    monkeypatch.setattr(
        session_mod, "messages_after", AsyncMock(return_value=_messages(11, 25))
    )
    set_summary = AsyncMock()
    monkeypatch.setattr(session_mod, "set_summary", set_summary)
    llm = AsyncMock(return_value={"summary": "新摘要"})
    monkeypatch.setattr(summary_mod, "llm_json", llm)
    monkeypatch.setattr(summary_mod, "ensure_token_budget", AsyncMock())

    folded = await summary_mod.maybe_summarize("s1", 1)

    assert folded == 17
    llm.assert_awaited_once()
    set_summary.assert_awaited_once()
    args = set_summary.await_args.args
    assert args[0] == "s1"
    assert args[1] == "新摘要"
    assert args[2] == 27  # last folded message id


@pytest.mark.asyncio
async def test_summarize_skips_small_batch(monkeypatch):
    monkeypatch.setattr(session_mod, "summary_state", AsyncMock(return_value=("", 0)))
    monkeypatch.setattr(
        session_mod, "messages_after", AsyncMock(return_value=_messages(1, 10))
    )
    llm = AsyncMock()
    monkeypatch.setattr(summary_mod, "llm_json", llm)

    assert await summary_mod.maybe_summarize("s1", 1) == 0
    llm.assert_not_awaited()


def test_summary_is_truncated_to_40_lines():
    text = "\n".join(f"line {i}" for i in range(80))
    out = summary_mod._truncate(text)
    assert len(out.splitlines()) == 40
    assert "line 39" in out and "line 40" not in out


def test_summary_injected_into_system_prompt():
    prompt = build_system_prompt([], [], summary="项目决定使用 FastAPI + SQLite")
    assert "早期会话摘要" in prompt
    assert "FastAPI + SQLite" in prompt


@pytest.mark.asyncio
async def test_recent_messages_skips_summarized_history(monkeypatch):
    query = AsyncMock(return_value=[("assistant", "a"), ("user", "b")])
    monkeypatch.setattr(session_mod, "query", query)

    rows = await session_mod.recent_messages("s1", limit=5, after_id=42)

    sql, params = query.await_args.args
    assert "id > %s" in sql
    assert params == ("s1", 42, 5)
    assert rows == [{"role": "user", "content": "b"}, {"role": "assistant", "content": "a"}]


@pytest.mark.asyncio
async def test_set_summary_records_upto_id(monkeypatch):
    execute = AsyncMock()
    monkeypatch.setattr(session_mod, "execute", execute)

    await session_mod.set_summary("s1", "摘要", 99)

    sql, params = execute.await_args.args
    assert "summary_upto_id" in sql
    assert params == ("摘要", 99, "s1")

"""Resumable turns: storage SQL, event log, executor and job-runner rules."""
import sys
from unittest.mock import AsyncMock

import psycopg
import pytest

from app.core.turns import store

store_module = sys.modules["app.core.turns.store"]


def _row(status="queued", cancel_requested=False):
    return (
        "t-1", "s-1", 7, status, cancel_requested, None,
        11, None, None, None, None, None,
    )


@pytest.mark.asyncio
async def test_create_turn_refuses_when_session_has_active_turn(monkeypatch):
    execute = AsyncMock(return_value=[])
    monkeypatch.setattr(store_module, "execute", execute)

    result = await store.create_turn("t-1", "s-1", 7, 11)

    assert result is None
    sql, params = execute.await_args.args
    assert "INSERT INTO turns" in sql
    assert "WHERE NOT EXISTS" in sql
    assert "status IN ('queued', 'running')" in sql
    assert params == ("t-1", "s-1", 7, 11, "s-1")


@pytest.mark.asyncio
async def test_create_turn_returns_none_on_unique_race(monkeypatch):
    execute = AsyncMock(side_effect=psycopg.errors.UniqueViolation())
    monkeypatch.setattr(store_module, "execute", execute)

    assert await store.create_turn("t-1", "s-1", 7, 11) is None


@pytest.mark.asyncio
async def test_active_turn_filters_by_owner(monkeypatch):
    query = AsyncMock(return_value=[_row()])
    monkeypatch.setattr(store_module, "query", query)

    turn = await store.get_active_turn("s-1", 7)

    assert turn["id"] == "t-1"
    sql, params = query.await_args.args
    assert "user_id = %s" in sql
    assert "status IN ('queued', 'running')" in sql
    assert params == ("s-1", 7)


@pytest.mark.asyncio
async def test_get_turn_filters_by_owner(monkeypatch):
    query = AsyncMock(return_value=[_row()])
    monkeypatch.setattr(store_module, "query", query)

    turn = await store.get_turn("t-1", 7)

    assert turn["id"] == "t-1"
    assert turn["status"] == "queued"
    sql, params = query.await_args.args
    assert "user_id = %s" in sql
    assert params == ("t-1", 7)


@pytest.mark.asyncio
async def test_request_cancel_marks_queued_turn_canceled(monkeypatch):
    execute = AsyncMock(return_value=[("canceled",)])
    monkeypatch.setattr(store_module, "execute", execute)

    status = await store.request_cancel("t-1")

    assert status == "canceled"
    sql, params = execute.await_args.args
    assert "cancel_requested = TRUE" in sql
    assert "status IN ('queued', 'running')" in sql
    assert params == ("t-1",)


@pytest.mark.asyncio
async def test_recover_marks_only_active_turns_interrupted(monkeypatch):
    execute = AsyncMock(return_value=[("t-1",), ("t-2",)])
    monkeypatch.setattr(store_module, "execute", execute)

    count = await store.recover_interrupted_turns()

    assert count == 2
    sql, _ = execute.await_args.args
    assert "status = 'interrupted'" in sql
    assert "status IN ('queued', 'running')" in sql


@pytest.mark.asyncio
async def test_finish_turn_cannot_overwrite_canceled_row(monkeypatch):
    execute = AsyncMock(return_value=[])
    monkeypatch.setattr(store_module, "execute", execute)

    await store.finish_turn("t-1", "succeeded", assistant_message_id=99)

    sql, params = execute.await_args.args
    assert "WHERE id = %s AND status IN ('queued', 'running')" in sql
    assert params == ("succeeded", None, 99, "t-1")


from app.core.turns import events  # noqa: E402

events_module = sys.modules["app.core.turns.events"]


def test_coalescer_merges_tokens_and_flushes_before_plain_event():
    coalescer = events.EventCoalescer()

    assert coalescer.feed({"event": "token", "data": {"text": "你"}}) == []
    assert coalescer.feed({"event": "token", "data": {"text": "好"}}) == []

    batch = coalescer.feed({"event": "tool_call", "data": {"id": "c1"}})

    assert [item[0] for item in batch] == ["token", "tool_call"]
    assert batch[0][1] == {"text": "你好"}


def test_coalescer_trims_tool_output_to_tail():
    coalescer = events.EventCoalescer()

    coalescer.feed({"event": "tool_output", "data": {
        "id": "c1", "stream": "stdout", "name": "run_command", "text": "x" * 70_000,
    }})
    batch = coalescer.flush()

    assert batch[0][0] == "tool_output"
    assert len(batch[0][1]["text"]) == events.TOOL_OUTPUT_LIMIT
    assert batch[0][1]["id"] == "c1"


def test_coalescer_flush_if_due_waits_for_interval():
    coalescer = events.EventCoalescer()
    coalescer.feed({"event": "token", "data": {"text": "a"}})

    assert coalescer.flush_if_due(now=coalescer._last_flush) == []  # noqa: SLF001
    assert coalescer.flush_if_due(
        now=coalescer._last_flush + events.FLUSH_INTERVAL_SECONDS + 0.1
    )[0][0] == "token"


@pytest.mark.asyncio
async def test_append_event_uses_conflict_safe_insert(monkeypatch):
    execute = AsyncMock(return_value=[])
    monkeypatch.setattr(events_module, "execute", execute)

    await events.append_event("t-1", 3, "token", {"text": "hi"})

    sql, params = execute.await_args.args
    assert "INSERT INTO turn_events" in sql
    assert "ON CONFLICT (turn_id, seq) DO NOTHING" in sql
    assert params[:3] == ("t-1", 3, "token")


@pytest.mark.asyncio
async def test_load_events_returns_ordered_payloads(monkeypatch):
    query = AsyncMock(return_value=[(1, "meta", {"a": 1}), (2, "token", {"text": "x"})])
    monkeypatch.setattr(events_module, "query", query)

    rows = await events.load_events("t-1", 0)

    assert [row["seq"] for row in rows] == [1, 2]
    sql, params = query.await_args.args
    assert "seq > %s" in sql
    assert params == ("t-1", 0, 200)


def test_coalescer_keeps_tokens_after_output_in_order():
    coalescer = events.EventCoalescer()

    assert coalescer.feed({"event": "token", "data": {"text": "A"}}) == []
    coalescer.feed({"event": "tool_output", "data": {
        "id": "c1", "stream": "stdout", "name": "run", "text": "O",
    }})

    batch = coalescer.feed({"event": "token", "data": {"text": "B"}})

    assert [item[0] for item in batch] == ["token", "tool_output"]
    assert batch[0][1] == {"text": "A"}
    assert batch[1][1]["text"] == "O"
    assert coalescer.flush() == [("token", {"text": "B"})]

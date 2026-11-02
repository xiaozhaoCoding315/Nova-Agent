"""Resumable turns: storage SQL, event log, executor and job-runner rules."""
import asyncio
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


from app.core.turns import service as turn_service  # noqa: E402

service_module = sys.modules["app.core.turns.service"]


def _install_executor_mocks(monkeypatch, *, status="queued"):
    monkeypatch.setattr(store, "get_turn", AsyncMock(return_value={
        "id": "t-1", "session_id": "s-1", "user_id": 7, "status": status,
        "user_message_id": 11, "cancel_requested": False, "job_id": None,
    }))
    monkeypatch.setattr(store, "start_turn", AsyncMock(return_value=True))
    finish = AsyncMock()
    monkeypatch.setattr(store, "finish_turn", finish)
    monkeypatch.setattr(store, "is_cancel_requested", AsyncMock(return_value=False))
    monkeypatch.setattr(
        service_module.session_mod, "get_session",
        AsyncMock(return_value={"id": "s-1", "repo_ids": ["r1"]}),
    )
    monkeypatch.setattr(
        service_module.session_mod, "get_message",
        AsyncMock(return_value={"content": "hi", "attachments": []}),
    )
    monkeypatch.setattr(
        service_module, "get_user_by_id",
        AsyncMock(return_value={"id": 7, "role": "demo"}),
    )
    monkeypatch.setattr(events, "max_seq", AsyncMock(return_value=0))
    appended: list[tuple[int, str, dict]] = []

    async def append(turn_id, seq, kind, payload):
        appended.append((seq, kind, payload))

    monkeypatch.setattr(events, "append_event", append)
    return finish, appended


@pytest.mark.asyncio
async def test_execute_turn_persists_events_and_marks_succeeded(monkeypatch):
    finish, appended = _install_executor_mocks(monkeypatch)

    async def fake_run_chat(*_args, **_kwargs):
        yield {"event": "meta", "data": {"session_id": "s-1"}}
        yield {"event": "token", "data": {"text": "hello"}}
        yield {"event": "done", "data": {"message_id": 77}}

    monkeypatch.setattr(service_module, "run_chat", fake_run_chat)

    status = await turn_service.execute_turn("t-1")

    assert status == "succeeded"
    assert [item[1] for item in appended] == ["meta", "token", "done"]
    finish.assert_awaited_once()
    assert finish.await_args.args == ("t-1", "succeeded")
    assert finish.await_args.kwargs["assistant_message_id"] == 77


@pytest.mark.asyncio
async def test_execute_turn_cancels_running_stream(monkeypatch):
    finish, _ = _install_executor_mocks(monkeypatch)
    monkeypatch.setattr(store, "is_cancel_requested", AsyncMock(return_value=True))

    async def fake_run_chat(*_args, **_kwargs):
        await asyncio.sleep(30)
        yield {"event": "done", "data": {}}

    monkeypatch.setattr(service_module, "run_chat", fake_run_chat)

    status = await asyncio.wait_for(turn_service.execute_turn("t-1"), timeout=3)

    assert status == "canceled"
    assert finish.await_args.args == ("t-1", "canceled")


@pytest.mark.asyncio
async def test_execute_turn_marks_missing_context_failed(monkeypatch):
    finish, _ = _install_executor_mocks(monkeypatch)
    monkeypatch.setattr(service_module.session_mod, "get_message", AsyncMock(return_value=None))

    status = await turn_service.execute_turn("t-1")

    assert status == "failed"
    assert "上下文" in finish.await_args.kwargs["error"]


class _OneShotLLM:
    async def astream_with_tools(self, messages, tools):
        yield {"type": "content", "content": "部分输出"}
        yield {"type": "usage", "usage": {
            "prompt_tokens": 1, "completion_tokens": 1, "model": "test",
        }}


@pytest.mark.asyncio
async def test_run_chat_persists_partial_output_when_closed(monkeypatch):
    from app.core.agent import loop as loop_mod

    async def _get_llm(*_args, **_kwargs):
        return _OneShotLLM()

    monkeypatch.setattr(loop_mod, "get_llm", _get_llm)
    monkeypatch.setattr(loop_mod, "get_registry", lambda: type(
        "R", (), {"specs": lambda self, **_kw: [], "get": lambda self, _n: None},
    )())
    monkeypatch.setattr(loop_mod, "retrieve", AsyncMock(return_value=[]))
    monkeypatch.setattr(loop_mod.session_mod, "recent_messages", AsyncMock(return_value=[]))
    add_message = AsyncMock(return_value=101)
    monkeypatch.setattr(loop_mod.session_mod, "add_message", add_message)
    monkeypatch.setattr(loop_mod.facts_mod, "get_relevant_facts", AsyncMock(return_value=[]))
    monkeypatch.setattr(loop_mod.facts_mod, "extract_facts_from_turn", AsyncMock())
    # Offline collaborators: the DB is not part of this unit test.
    monkeypatch.setattr(loop_mod, "trace_record", AsyncMock())
    monkeypatch.setattr(loop_mod, "ensure_token_budget", AsyncMock())
    monkeypatch.setattr(loop_mod, "log_audit", AsyncMock())
    monkeypatch.setattr(loop_mod, "_record_usage", AsyncMock())
    monkeypatch.setattr(loop_mod, "local_agent_online", AsyncMock(return_value=False))
    from app.core import reflection
    monkeypatch.setattr(reflection, "lessons_for_context", AsyncMock(return_value=[]))

    session = {
        "id": "11111111-1111-1111-1111-111111111111",
        "title": "t", "permission_mode": "ask", "model": "m",
        "llm_overrides": {},
    }
    generator = loop_mod.run_chat(
        {"id": 1, "username": "u", "role": "demo"}, session, "hi", [],
        persist_on_cancel=True,
    )
    async for event in generator:
        if event["event"] == "token":
            break
    await generator.aclose()

    add_message.assert_awaited()
    assert add_message.await_args.args[2] == "部分输出"


@pytest.mark.asyncio
async def test_execute_turn_cancels_during_continuous_stream(monkeypatch):
    finish, _ = _install_executor_mocks(monkeypatch)
    checks = {"n": 0}

    async def cancel_check(_turn_id):
        checks["n"] += 1
        return checks["n"] >= 2

    monkeypatch.setattr(store, "is_cancel_requested", cancel_check)

    async def fake_run_chat(*_args, **_kwargs):
        for _ in range(100):
            await asyncio.sleep(0.05)
            yield {"event": "token", "data": {"text": "x"}}
        yield {"event": "done", "data": {}}

    monkeypatch.setattr(service_module, "run_chat", fake_run_chat)

    status = await asyncio.wait_for(turn_service.execute_turn("t-1"), timeout=3)

    assert status == "canceled"
    assert finish.await_args.args == ("t-1", "canceled")
    assert checks["n"] >= 2


@pytest.mark.asyncio
async def test_execute_turn_marks_failed_when_context_load_errors(monkeypatch):
    finish, _ = _install_executor_mocks(monkeypatch)
    monkeypatch.setattr(
        service_module.session_mod, "get_session",
        AsyncMock(side_effect=RuntimeError("db down")),
    )

    status = await turn_service.execute_turn("t-1")

    assert status == "failed"
    assert finish.await_args.args == ("t-1", "failed")
    assert "RuntimeError" in finish.await_args.kwargs["error"]


def test_turn_routes_are_exposed():
    from app.api.v1 import chat as chat_api

    paths = {route.path for route in chat_api.router.routes}
    assert "/chat/message" in paths
    assert "/chat/turns/{turn_id}" in paths
    assert "/chat/turns/{turn_id}/stream" in paths
    assert "/chat/turns/{turn_id}/cancel" in paths
    assert "/chat/sessions/{session_id}/turns/active" in paths

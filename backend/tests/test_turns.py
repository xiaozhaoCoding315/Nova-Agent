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


@pytest.mark.asyncio
async def test_get_latest_turn_orders_and_filters_by_owner(monkeypatch):
    query = AsyncMock(return_value=[_row()])
    monkeypatch.setattr(store_module, "query", query)

    await store.get_latest_turn("s-1", 7)

    sql, params = query.await_args.args
    assert "ORDER BY created_at DESC, id DESC" in sql
    assert params == ("s-1", 7)


@pytest.mark.asyncio
async def test_cleanup_old_turns_deletes_only_terminal_statuses(monkeypatch):
    execute = AsyncMock(return_value=[("t-1",)])
    monkeypatch.setattr(store_module, "execute", execute)

    count = await store.cleanup_old_turns(30)

    assert count == 1
    sql, params = execute.await_args.args
    assert "status = ANY(%s)" in sql
    assert params == (list(store.TERMINAL_STATUSES), 30)


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


def test_sse_frame_formats_event_and_json():
    frame = events.sse_frame("token", {"text": "你好"})

    assert frame == 'event: token\ndata: {"text": "你好"}\n\n'


def test_coalescer_flushes_at_token_threshold():
    coalescer = events.EventCoalescer()

    assert coalescer.feed({"event": "token", "data": {"text": "a" * 799}}) == []
    batch = coalescer.feed({"event": "token", "data": {"text": "b"}})

    assert batch == [("token", {"text": "a" * 799 + "b"})]


def test_coalescer_merges_output_by_id_and_stream():
    coalescer = events.EventCoalescer()
    for text, stream, call_id in (
        ("a", "stdout", "c1"),
        ("b", "stderr", "c1"),
        ("c", "stdout", "c2"),
    ):
        coalescer.feed({"event": "tool_output", "data": {
            "id": call_id, "stream": stream, "name": "run", "text": text,
        }})

    batch = coalescer.flush()

    assert [
        (kind, payload["id"], payload["stream"], payload["text"])
        for kind, payload in batch
    ] == [
        ("tool_output", "c1", "stdout", "a"),
        ("tool_output", "c1", "stderr", "b"),
        ("tool_output", "c2", "stdout", "c"),
    ]


@pytest.mark.asyncio
async def test_load_events_clamps_limit(monkeypatch):
    query = AsyncMock(return_value=[])
    monkeypatch.setattr(events_module, "query", query)

    await events.load_events("t-1", -5, limit=900)

    _, params = query.await_args.args
    assert params == ("t-1", 0, 500)


@pytest.mark.asyncio
async def test_max_seq_returns_zero_without_rows(monkeypatch):
    monkeypatch.setattr(events_module, "query", AsyncMock(return_value=[]))

    assert await events.max_seq("t-1") == 0


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


@pytest.mark.asyncio
async def test_tail_turn_drains_all_pages_on_terminal(monkeypatch):
    from app.api.v1 import chat as chat_api

    pages = [
        [{"seq": i, "type": "token", "payload": {"text": str(i)}} for i in range(1, 201)],
        [{"seq": i, "type": "token", "payload": {"text": str(i)}} for i in range(201, 401)],
        [{"seq": i, "type": "token", "payload": {"text": str(i)}} for i in range(401, 451)],
        [],
    ]
    calls = {"n": 0}

    async def fake_load(_turn_id, after_seq, **_kwargs):
        page = pages[min(calls["n"], len(pages) - 1)]
        calls["n"] += 1
        return [row for row in page if row["seq"] > after_seq]

    monkeypatch.setattr(chat_api.turn_events, "load_events", fake_load)
    monkeypatch.setattr(chat_api.turn_store, "get_turn", AsyncMock(return_value={
        "id": "t-1", "session_id": "s-1", "status": "succeeded",
    }))

    class FakeRequest:
        async def is_disconnected(self):
            return False

    frames = [frame async for frame in chat_api._tail_turn("t-1", FakeRequest())]

    assert len(frames) == 1 + 450  # synthetic turn frame + every persisted event
    assert '"text": "450"' in frames[-1]


@pytest.mark.asyncio
async def test_execute_turn_flushes_tokens_during_continuous_stream(monkeypatch):
    _finish, appended = _install_executor_mocks(monkeypatch)
    monkeypatch.setattr(events, "FLUSH_INTERVAL_SECONDS", 0.05)

    async def fake_run_chat(*_args, **_kwargs):
        for index in range(40):
            await asyncio.sleep(0.01)
            yield {"event": "token", "data": {"text": f"{index},"}}
        yield {"event": "done", "data": {"message_id": 5}}

    monkeypatch.setattr(service_module, "run_chat", fake_run_chat)

    status = await turn_service.execute_turn("t-1")

    assert status == "succeeded"
    token_events = [payload for _, kind, payload in appended if kind == "token"]
    # Without the per-iteration flush_if_due, all ~120 chars are written once
    # when the generator ends instead of in ~0.05s slices while it runs.
    assert len(token_events) >= 2
    assert all(len(payload["text"]) < 800 for payload in token_events)


@pytest.mark.asyncio
async def test_execute_turn_drains_completed_pending_after_timeout(monkeypatch):
    finish, appended = _install_executor_mocks(monkeypatch)
    real_wait_for = asyncio.wait_for
    calls = {"n": 0}

    async def fake_wait_for(awaitable, timeout):
        calls["n"] += 1
        if calls["n"] == 1:
            # Let the shielded __anext__ task finish, then report a timeout so
            # the executor's pending.done() drain branch is exercised.
            await asyncio.sleep(0.02)
            raise TimeoutError
        return await real_wait_for(awaitable, timeout)

    monkeypatch.setattr(service_module.asyncio, "wait_for", fake_wait_for)

    async def fake_run_chat(*_args, **_kwargs):
        yield {"event": "done", "data": {"message_id": 9}}

    monkeypatch.setattr(service_module, "run_chat", fake_run_chat)

    status = await turn_service.execute_turn("t-1")

    assert status == "succeeded"
    assert calls["n"] == 2
    assert [kind for _, kind, _ in appended] == ["done"]
    assert finish.await_args.kwargs["assistant_message_id"] == 9


@pytest.mark.asyncio
async def test_execute_turn_redacts_failure_before_persisting(monkeypatch):
    finish, _ = _install_executor_mocks(monkeypatch)
    secret = "sk-" + "a" * 24

    async def fake_run_chat(*_args, **_kwargs):
        raise RuntimeError(f"upstream rejected {secret}")
        yield {}  # pragma: no cover - makes this an async generator

    monkeypatch.setattr(service_module, "run_chat", fake_run_chat)

    status = await turn_service.execute_turn("t-1")

    assert status == "failed"
    error = finish.await_args.kwargs["error"]
    assert secret not in error
    assert "[REDACTED]" in error

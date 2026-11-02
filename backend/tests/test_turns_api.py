"""Endpoint contracts for resumable turns: 409, headers, ownership, cancel."""
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from app.api.v1 import chat as chat_api
from app.core.jobs.runner import runner as job_runner
from app.models.schemas import ChatRequest

USER = {"id": 7, "username": "u", "role": "demo"}
SESSION = {
    "id": "s-1",
    "model": "m",
    "permission_mode": "ask",
    "repo_ids": [],
    "llm_overrides": {},
}


class FakeRequest:
    async def is_disconnected(self):
        return False


def _install_chat_mocks(monkeypatch):
    monkeypatch.setattr(chat_api, "check_chat_quota", AsyncMock())
    monkeypatch.setattr(
        chat_api.session_mod, "get_session",
        AsyncMock(return_value=dict(SESSION)),
    )
    monkeypatch.setattr(chat_api.turn_store, "get_active_turn", AsyncMock(return_value=None))
    add_message = AsyncMock(return_value=11)
    monkeypatch.setattr(chat_api.session_mod, "add_message", add_message)
    monkeypatch.setattr(
        chat_api.session_mod, "maybe_set_title", AsyncMock(return_value="title"),
    )
    monkeypatch.setattr(chat_api, "trace_record", AsyncMock())
    monkeypatch.setattr(chat_api, "execute", AsyncMock())
    create_turn = AsyncMock(return_value={"id": "t-1"})
    monkeypatch.setattr(chat_api.turn_store, "create_turn", create_turn)
    enqueue = AsyncMock(return_value="j-1")
    monkeypatch.setattr(chat_api.jobs_service, "enqueue_chat_turn", enqueue)
    set_job_id = AsyncMock()
    monkeypatch.setattr(chat_api.turn_store, "set_job_id", set_job_id)
    start_inline = Mock()
    monkeypatch.setattr(chat_api.turn_service, "start_turn_task", start_inline)

    async def fake_tail(_turn_id, _request, after_seq=0):
        yield "event: turn\ndata: {}\n\n"

    monkeypatch.setattr(chat_api, "_tail_turn", fake_tail)
    return add_message, create_turn, enqueue, set_job_id, start_inline


@pytest.mark.asyncio
async def test_chat_message_rejects_while_turn_is_active(monkeypatch):
    add_message, *_ = _install_chat_mocks(monkeypatch)
    monkeypatch.setattr(
        chat_api.turn_store, "get_active_turn",
        AsyncMock(return_value={"id": "t-active"}),
    )

    with pytest.raises(HTTPException) as exc:
        await chat_api.chat_message(
            ChatRequest(session_id="s-1", content="hi"),
            request=FakeRequest(),
            user=USER,
        )

    assert exc.value.status_code == 409
    add_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_chat_message_rolls_back_user_message_on_create_race(monkeypatch):
    _, create_turn, *_ = _install_chat_mocks(monkeypatch)
    create_turn.return_value = None

    with pytest.raises(HTTPException) as exc:
        await chat_api.chat_message(
            ChatRequest(session_id="s-1", content="hi"),
            request=FakeRequest(),
            user=USER,
        )

    assert exc.value.status_code == 409
    sql, params = chat_api.execute.await_args.args
    assert "DELETE FROM messages" in sql
    assert params == (11,)


@pytest.mark.asyncio
async def test_chat_message_returns_turn_headers_and_enqueues(monkeypatch):
    _, create_turn, enqueue, set_job_id, start_inline = _install_chat_mocks(monkeypatch)
    create_turn.side_effect = lambda turn_id, *_args: {"id": turn_id}

    response = await chat_api.chat_message(
        ChatRequest(session_id="s-1", content="hi"),
        request=FakeRequest(),
        user=USER,
    )

    turn_id = create_turn.await_args.args[0]
    assert response.headers["x-turn-id"] == turn_id
    assert response.headers["x-session-id"] == "s-1"
    enqueue.assert_awaited_once()
    set_job_id.assert_awaited_once_with(turn_id, "j-1")
    start_inline.assert_not_called()


@pytest.mark.asyncio
async def test_chat_message_starts_inline_when_runner_disabled(monkeypatch):
    _, create_turn, enqueue, set_job_id, start_inline = _install_chat_mocks(monkeypatch)
    enqueue.return_value = None

    await chat_api.chat_message(
        ChatRequest(session_id="s-1", content="hi"),
        request=FakeRequest(),
        user=USER,
    )

    set_job_id.assert_not_awaited()
    start_inline.assert_called_once_with(create_turn.await_args.args[0])


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", ["status", "stream", "cancel"])
async def test_turn_endpoints_hide_other_users_turns(monkeypatch, endpoint):
    monkeypatch.setattr(chat_api.turn_store, "get_turn", AsyncMock(return_value=None))

    with pytest.raises(HTTPException) as exc:
        if endpoint == "status":
            await chat_api.get_turn_status("t-1", user=USER)
        elif endpoint == "stream":
            await chat_api.stream_turn(
                "t-1", request=FakeRequest(), after_seq=0, user=USER,
            )
        else:
            await chat_api.cancel_turn("t-1", user=USER)

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_active_turn_hides_other_users_sessions(monkeypatch):
    monkeypatch.setattr(chat_api.session_mod, "get_session", AsyncMock(return_value=None))

    with pytest.raises(HTTPException) as exc:
        await chat_api.active_turn("s-1", user=USER)

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_cancel_active_turn_requests_turn_and_job_cancel(monkeypatch):
    monkeypatch.setattr(
        chat_api.turn_store, "get_turn",
        AsyncMock(return_value={"id": "t-1", "status": "running", "job_id": "j-1"}),
    )
    request_cancel = AsyncMock(return_value="running")
    monkeypatch.setattr(chat_api.turn_store, "request_cancel", request_cancel)
    cancel_job = AsyncMock(return_value={"id": "j-1"})
    monkeypatch.setattr(job_runner, "cancel", cancel_job)

    result = await chat_api.cancel_turn("t-1", user=USER)

    assert result == {"ok": True, "canceled": True}
    request_cancel.assert_awaited_once_with("t-1")
    cancel_job.assert_awaited_once_with("j-1", 7)


@pytest.mark.asyncio
async def test_cancel_terminal_turn_is_a_noop(monkeypatch):
    monkeypatch.setattr(
        chat_api.turn_store, "get_turn",
        AsyncMock(return_value={"id": "t-1", "status": "succeeded", "job_id": "j-1"}),
    )
    request_cancel = AsyncMock()
    monkeypatch.setattr(chat_api.turn_store, "request_cancel", request_cancel)

    result = await chat_api.cancel_turn("t-1", user=USER)

    assert result == {"ok": True, "canceled": False}
    request_cancel.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_session_cancels_active_turn_before_deleting(monkeypatch):
    order: list[str] = []
    monkeypatch.setattr(
        chat_api.session_mod, "get_session",
        AsyncMock(return_value={"id": "s-1"}),
    )
    monkeypatch.setattr(
        chat_api.turn_store, "get_active_turn",
        AsyncMock(return_value={"id": "t-1", "job_id": "j-1"}),
    )

    async def request_cancel(_turn_id):
        order.append("cancel_turn")

    async def cancel_job(_job_id, _user_id):
        order.append("cancel_job")

    async def delete_session(_session_id, _user_id):
        order.append("delete")
        return True

    monkeypatch.setattr(chat_api.turn_store, "request_cancel", request_cancel)
    monkeypatch.setattr(job_runner, "cancel", cancel_job)
    monkeypatch.setattr(chat_api.session_mod, "delete_session", delete_session)

    result = await chat_api.delete_session("s-1", user=USER)

    assert result == {"ok": True}
    assert order == ["cancel_turn", "cancel_job", "delete"]

"""Resumable turns: storage SQL, event log, executor and job-runner rules."""
import sys
from unittest.mock import AsyncMock

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

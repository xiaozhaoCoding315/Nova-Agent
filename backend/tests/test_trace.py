"""Trajectory recording tests (DB mocked)."""
from unittest.mock import AsyncMock

import pytest

from app.core import trace


@pytest.mark.asyncio
async def test_record_persists_payload(monkeypatch):
    mock = AsyncMock(return_value=[])
    monkeypatch.setattr(trace, "execute", mock)
    await trace.record("session-1", "turn-1", "tool_call", {"name": "read_file"})
    mock.assert_awaited_once()
    sql, params = mock.await_args.args
    assert "INSERT INTO trace_events" in sql
    assert params[0] == "session-1"
    assert params[1] == "turn-1"
    assert params[2] == "tool_call"
    assert '"name": "read_file"' in params[3]


@pytest.mark.asyncio
async def test_record_never_raises(monkeypatch):
    monkeypatch.setattr(trace, "execute", AsyncMock(side_effect=RuntimeError("db down")))
    await trace.record("s", "t", "error", {"message": "x"})  # must not raise
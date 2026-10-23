"""Session management helpers."""
from unittest.mock import AsyncMock

import pytest

from app.core.memory import session as session_mod


@pytest.mark.asyncio
async def test_rename_session_updates_owner_scoped_title(monkeypatch):
    execute = AsyncMock(return_value=[("s1", "新标题", None, None)])
    monkeypatch.setattr(session_mod, "execute", execute)

    result = await session_mod.rename_session("s1", 7, "新标题")

    sql, params = execute.await_args.args
    assert "UPDATE sessions SET title" in sql
    assert "user_id = %s" in sql
    assert params == ("新标题", "s1", 7)
    assert result == {"id": "s1", "title": "新标题", "created_at": None, "updated_at": None}


@pytest.mark.asyncio
async def test_rename_session_returns_none_when_not_owned(monkeypatch):
    monkeypatch.setattr(session_mod, "execute", AsyncMock(return_value=[]))
    assert await session_mod.rename_session("s1", 7, "x") is None

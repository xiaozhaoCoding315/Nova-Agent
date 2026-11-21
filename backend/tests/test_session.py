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


@pytest.mark.asyncio
async def test_list_sessions_filters_by_project(monkeypatch):
    query = AsyncMock(return_value=[(
        "s1", "登录需求", None, None, 3, "ask",
        ["11111111-1111-1111-1111-111111111111"], "qwen3.8-max",
        "11111111-1111-1111-1111-111111111111", {"model": "glm-4.6"},
        "dev", None,
    )])
    monkeypatch.setattr(session_mod, "query", query)

    result = await session_mod.list_sessions(
        7, repo_id="11111111-1111-1111-1111-111111111111"
    )

    sql, params = query.await_args.args
    assert "session_repos" in sql
    assert params[0] == 7
    assert params[1] == "11111111-1111-1111-1111-111111111111"
    assert params[2] == "dev"
    assert result[0]["primary_repo_id"] == "11111111-1111-1111-1111-111111111111"
    assert result[0]["repo_ids"] == ["11111111-1111-1111-1111-111111111111"]
    assert result[0]["product_mode"] == "dev"


@pytest.mark.asyncio
async def test_list_sessions_scopes_thesis_history(monkeypatch):
    query = AsyncMock(return_value=[(
        "s2", "写第三章", None, None, 1, "ask", [], None, None, {},
        "thesis", "22222222-2222-2222-2222-222222222222",
    )])
    monkeypatch.setattr(session_mod, "query", query)

    result = await session_mod.list_sessions(
        7,
        product_mode="thesis",
        thesis_project_id="22222222-2222-2222-2222-222222222222",
    )

    sql, params = query.await_args.args
    assert "s.product_mode = %s" in sql
    assert "s.thesis_project_id = %s" in sql
    assert params[:3] == (
        7, "thesis", "22222222-2222-2222-2222-222222222222",
    )
    assert result[0]["thesis_project_id"] == "22222222-2222-2222-2222-222222222222"


@pytest.mark.asyncio
async def test_set_repo_ids_replaces_join_rows_and_primary(monkeypatch):
    transaction = AsyncMock()
    monkeypatch.setattr(session_mod, "transaction", transaction)

    await session_mod.set_repo_ids("s1", ["repo-a", "repo-b", "repo-a"])

    statements = transaction.await_args.args[0]
    assert "DELETE FROM session_repos" in statements[0][0]
    inserts = [sql for sql, _ in statements if "INSERT INTO session_repos" in sql]
    assert len(inserts) == 2
    update_sql, update_params = statements[-1]
    assert "primary_repo_id" in update_sql
    assert update_params[0] == "repo-a"
    assert update_params[2] == "s1"

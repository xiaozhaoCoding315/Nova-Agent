"""Per-session LLM overrides: validation, persistence and merge semantics."""
import json
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.core.memory import session as session_mod
from app.models.schemas import LlmOverrides, SessionUpdateRequest


def test_overrides_are_optional_and_validated():
    assert SessionUpdateRequest().llm_overrides is None
    with pytest.raises(ValidationError):
        LlmOverrides(reasoning_effort="ultra")
    with pytest.raises(ValidationError):
        LlmOverrides(max_tokens=0)
    body = SessionUpdateRequest(
        llm_overrides={"provider": "zhipu", "model": "glm-4.6", "temperature": 0.2},
    )
    assert body.llm_overrides.provider == "zhipu"
    assert body.llm_overrides.temperature == 0.2


@pytest.mark.asyncio
async def test_create_session_persists_overrides(monkeypatch):
    execute = AsyncMock(return_value=[])
    monkeypatch.setattr(session_mod, "execute", execute)

    overrides = {"provider": "zhipu", "temperature": 0.2}
    session = await session_mod.create_session(7, title="t", llm_overrides=overrides)

    sql, params = execute.await_args.args
    assert "llm_overrides" in sql
    assert "::jsonb" in sql
    assert json.loads(params[4]) == overrides
    assert session["llm_overrides"] == overrides


@pytest.mark.asyncio
async def test_get_session_returns_overrides(monkeypatch):
    overrides = {"provider": "anthropic", "model": "claude-sonnet-5"}
    query = AsyncMock(return_value=[(
        "s1", "t", None, "ask", None, None, [], 0, "legacy-model", None, overrides,
    )])
    monkeypatch.setattr(session_mod, "query", query)

    session = await session_mod.get_session("s1", 7)

    sql, _ = query.await_args.args
    assert "s.llm_overrides" in sql
    assert session["llm_overrides"] == overrides


@pytest.mark.asyncio
async def test_list_sessions_returns_overrides(monkeypatch):
    overrides = {"model": "glm-4.6", "reasoning_effort": "high"}
    query = AsyncMock(return_value=[(
        "s1", "t", None, None, 2, "ask", [], "legacy-model", None, overrides,
    )])
    monkeypatch.setattr(session_mod, "query", query)

    sessions = await session_mod.list_sessions(7)

    sql, _ = query.await_args.args
    assert "s.llm_overrides" in sql
    assert sessions[0]["llm_overrides"] == overrides


@pytest.mark.asyncio
async def test_update_llm_overrides_merges_and_returns_returning(monkeypatch):
    execute = AsyncMock(return_value=[({"provider": "zhipu", "model": "glm-4.6"},)])
    monkeypatch.setattr(session_mod, "execute", execute)

    merged = await session_mod.update_llm_overrides("s1", 7, {"model": "glm-4.6"})

    sql, params = execute.await_args.args
    assert "COALESCE(llm_overrides, '{}'::jsonb) || %s::jsonb" in sql
    assert "RETURNING llm_overrides" in sql
    assert "user_id = %s" in sql
    assert params == (json.dumps({"model": "glm-4.6"}, ensure_ascii=False), "s1", 7)
    assert merged == {"provider": "zhipu", "model": "glm-4.6"}


@pytest.mark.asyncio
async def test_update_llm_overrides_returns_none_when_not_owned(monkeypatch):
    monkeypatch.setattr(session_mod, "execute", AsyncMock(return_value=[]))

    assert await session_mod.update_llm_overrides("s1", 7, {"model": "glm-4.6"}) is None


@pytest.mark.asyncio
async def test_empty_overrides_merge_is_a_noop(monkeypatch):
    existing = {"provider": "zhipu", "model": "glm-4.6"}
    execute = AsyncMock(return_value=[(existing,)])
    monkeypatch.setattr(session_mod, "execute", execute)

    merged = await session_mod.update_llm_overrides("s1", 7, {})

    _, params = execute.await_args.args
    # `existing || '{}'` keeps every stored key, so an empty patch changes nothing.
    assert params[0] == "{}"
    assert merged == existing

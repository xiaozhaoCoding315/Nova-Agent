"""Long-term facts must be deduplicated per user, not globally."""
from unittest.mock import AsyncMock

import pytest

from app.core.embedding import embedder as embedder_mod
from app.core.memory import facts as facts_mod


class FakeEmbedder:
    async def embed(self, texts):
        return [[0.1, 0.2] for _ in texts]


@pytest.mark.asyncio
async def test_add_fact_dedup_and_insert_are_user_scoped(monkeypatch):
    query = AsyncMock(side_effect=[[], [(0,)]])
    execute = AsyncMock(side_effect=[[(42,)], []])
    monkeypatch.setattr(facts_mod, "query", query)
    monkeypatch.setattr(facts_mod, "execute", execute)
    monkeypatch.setattr(facts_mod, "_is_semantic_duplicate", AsyncMock(return_value=False))
    monkeypatch.setattr(embedder_mod, "get_embedder", lambda: FakeEmbedder())

    assert await facts_mod.add_fact(7, "偏好 FastAPI") is True

    dedup_sql, dedup_params = query.await_args_list[0].args
    assert "user_id = %s AND hash = %s" in dedup_sql
    assert dedup_params == (7, facts_mod._content_hash("偏好 FastAPI"))

    insert_sql, insert_params = execute.await_args_list[0].args
    assert "ON CONFLICT (user_id, hash)" in insert_sql
    assert insert_params[0] == 7
    assert "INSERT INTO fact_days" in execute.await_args_list[1].args[0]


@pytest.mark.asyncio
async def test_existing_fact_updates_only_its_owner(monkeypatch):
    query = AsyncMock(return_value=[(1,)])
    execute = AsyncMock(side_effect=[[], []])
    monkeypatch.setattr(facts_mod, "query", query)
    monkeypatch.setattr(facts_mod, "execute", execute)

    assert await facts_mod.add_fact(9, "偏好 FastAPI") is False

    update_sql, update_params = execute.await_args_list[0].args
    assert "WHERE user_id = %s AND hash = %s" in update_sql
    assert update_params == (9, facts_mod._content_hash("偏好 FastAPI"))
    assert "INSERT INTO fact_days" in execute.await_args_list[1].args[0]


class QueryEmbedder:
    async def embed(self, texts):
        return [[1.0, 0.0] for _ in texts]


@pytest.mark.asyncio
async def test_relevant_facts_blend_semantics_and_importance(monkeypatch):
    rows = [
        (1, "偏好 FastAPI", [1.0, 0.0], 1.0),
        (2, "使用 Java 后端", [0.0, 1.0], 2.0),
    ]
    monkeypatch.setattr(facts_mod, "query", AsyncMock(return_value=rows))
    execute = AsyncMock()
    monkeypatch.setattr(facts_mod, "execute", execute)
    monkeypatch.setattr(embedder_mod, "get_embedder", lambda: QueryEmbedder())

    facts = await facts_mod.get_relevant_facts(1, "FastAPI 项目", limit=2)

    assert facts == ["偏好 FastAPI", "使用 Java 后端"]
    assert "UPDATE facts SET last_used_at" in execute.await_args.args[0]


@pytest.mark.asyncio
async def test_promote_facts_requires_multiple_days(monkeypatch):
    execute = AsyncMock(return_value=[(1,), (2,)])
    monkeypatch.setattr(facts_mod, "execute", execute)

    assert await facts_mod.promote_facts() == 2
    sql = execute.await_args.args[0]
    assert "COUNT(DISTINCT day) >= 2" in sql
    assert "promoted_at IS NULL" in sql

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
    execute = AsyncMock()
    monkeypatch.setattr(facts_mod, "query", query)
    monkeypatch.setattr(facts_mod, "execute", execute)
    monkeypatch.setattr(facts_mod, "_is_semantic_duplicate", AsyncMock(return_value=False))
    monkeypatch.setattr(embedder_mod, "get_embedder", lambda: FakeEmbedder())

    assert await facts_mod.add_fact(7, "偏好 FastAPI") is True

    dedup_sql, dedup_params = query.await_args_list[0].args
    assert "user_id = %s AND hash = %s" in dedup_sql
    assert dedup_params == (7, facts_mod._content_hash("偏好 FastAPI"))

    insert_sql, insert_params = execute.await_args.args
    assert "ON CONFLICT (user_id, hash)" in insert_sql
    assert insert_params[0] == 7


@pytest.mark.asyncio
async def test_existing_fact_updates_only_its_owner(monkeypatch):
    query = AsyncMock(return_value=[(1,)])
    execute = AsyncMock()
    monkeypatch.setattr(facts_mod, "query", query)
    monkeypatch.setattr(facts_mod, "execute", execute)

    assert await facts_mod.add_fact(9, "偏好 FastAPI") is False

    update_sql, update_params = execute.await_args.args
    assert "WHERE user_id = %s AND hash = %s" in update_sql
    assert update_params == (9, facts_mod._content_hash("偏好 FastAPI"))

"""Optional pgvector index for facts, with a JSONB fallback when unavailable."""
from unittest.mock import AsyncMock

import pytest

from app.core.memory import scope as scope_mod
from app.core.memory import vector_store


@pytest.fixture(autouse=True)
def _reset_enabled(monkeypatch):
    monkeypatch.setattr(vector_store, "_ENABLED", None)


@pytest.mark.asyncio
async def test_rank_is_disabled_until_schema_is_ensured(monkeypatch):
    query = AsyncMock(side_effect=AssertionError("must not query when disabled"))
    monkeypatch.setattr(vector_store, "query", query)
    monkeypatch.setattr(vector_store, "_ENABLED", False)

    assert await vector_store.rank_fact_ids(7, [0.1, 0.2], [], 8) is None
    query.assert_not_awaited()


@pytest.mark.asyncio
async def test_rank_uses_cosine_distance_and_scope_filter(monkeypatch):
    monkeypatch.setattr(vector_store, "_ENABLED", True)
    query = AsyncMock(return_value=[(3,), (1,)])
    monkeypatch.setattr(vector_store, "query", query)

    ids = await vector_store.rank_fact_ids(
        7, [0.1, 0.2],
        [scope_mod.Scope("global", ""), scope_mod.Scope("repo", "r1")],
        8,
    )

    sql, params = query.await_args.args
    assert "<=>" in sql
    assert "f.status = 'active'" in sql
    assert "(f.scope_type = %s AND f.scope_id = %s)" in sql
    assert params[-1] == 8
    assert "[0.1, 0.2]" in params
    assert ids == [3, 1]


@pytest.mark.asyncio
async def test_ensure_schema_enables_pgvector_when_extension_exists(monkeypatch):
    query = AsyncMock(return_value=[(1,)])
    execute = AsyncMock()
    monkeypatch.setattr(vector_store, "query", query)
    monkeypatch.setattr(vector_store, "execute", execute)

    assert await vector_store.ensure_schema() is True
    assert vector_store._ENABLED is True
    sqls = [call.args[0] for call in execute.await_args_list]
    assert any("CREATE TABLE IF NOT EXISTS fact_vectors" in sql for sql in sqls)
    assert any("vector_cosine_ops" in sql for sql in sqls)


@pytest.mark.asyncio
async def test_ensure_schema_falls_back_when_extension_missing(monkeypatch):
    monkeypatch.setattr(vector_store, "query", AsyncMock(return_value=[]))
    execute = AsyncMock(side_effect=RuntimeError("extension not available"))
    monkeypatch.setattr(vector_store, "execute", execute)

    assert await vector_store.ensure_schema() is False
    assert vector_store._ENABLED is False


@pytest.mark.asyncio
async def test_index_fact_is_a_noop_without_pgvector(monkeypatch):
    monkeypatch.setattr(vector_store, "_ENABLED", False)
    execute = AsyncMock()
    monkeypatch.setattr(vector_store, "execute", execute)

    await vector_store.index_fact(1, 7, [0.1, 0.2])

    execute.assert_not_awaited()

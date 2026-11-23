"""Optional pgvector index for daily and session summaries."""
from datetime import date
from unittest.mock import AsyncMock

import pytest

from app.core.embedding import embedder as embedder_mod
from app.core.memory import episodic as episodic_mod
from app.core.memory import vector_store
from app.core.memory.scope import Scope


class FakeEmbedder:
    async def embed(self, texts):
        return [[0.1, 0.2] for _ in texts]


def _enable(monkeypatch):
    monkeypatch.setattr(vector_store, "_ENABLED", True)
    monkeypatch.setattr(embedder_mod, "get_embedder", lambda: FakeEmbedder())


@pytest.mark.asyncio
async def test_index_daily_embeds_and_upserts(monkeypatch):
    _enable(monkeypatch)
    execute = AsyncMock()
    monkeypatch.setattr(vector_store, "execute", execute)

    indexed = await vector_store.index_daily(
        7, "dev", "", date(2026, 11, 21), "完成 P1 记忆能力",
    )

    assert indexed is True
    sql, params = execute.await_args.args
    assert "summary_vectors" in sql
    assert params[0] == "daily:7:dev::2026-11-21"
    assert params[2] == "daily"
    assert params[5] == "完成 P1 记忆能力"


@pytest.mark.asyncio
async def test_index_session_uses_single_repo_scope(monkeypatch):
    _enable(monkeypatch)
    execute = AsyncMock()
    monkeypatch.setattr(vector_store, "execute", execute)
    monkeypatch.setattr(
        vector_store, "query",
        AsyncMock(return_value=[("dev", "", 1, "r1")]),
    )

    await vector_store.index_session(7, "sess-1", "会话摘要")

    _, params = execute.await_args.args
    assert params[0] == "session:sess-1"
    assert params[3] == "repo"
    assert params[4] == "r1"


@pytest.mark.asyncio
async def test_index_session_uses_thesis_scope(monkeypatch):
    _enable(monkeypatch)
    execute = AsyncMock()
    monkeypatch.setattr(vector_store, "execute", execute)
    monkeypatch.setattr(
        vector_store, "query",
        AsyncMock(return_value=[("thesis", "p1", 0, None)]),
    )

    await vector_store.index_session(7, "sess-2", "论文摘要")

    _, params = execute.await_args.args
    assert params[3] == "thesis"
    assert params[4] == "p1"


@pytest.mark.asyncio
async def test_index_daily_is_noop_when_vectors_disabled(monkeypatch):
    monkeypatch.setattr(vector_store, "_ENABLED", False)
    execute = AsyncMock()
    monkeypatch.setattr(vector_store, "execute", execute)

    assert await vector_store.index_daily(7, "dev", "", date.today(), "x") is False
    execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_rank_summaries_filters_readable_scopes(monkeypatch):
    monkeypatch.setattr(vector_store, "_ENABLED", True)
    query = AsyncMock(return_value=[(
        "daily:7:dev::2026-11-20", "daily", "dev", "", "摘要", None,
    )])
    monkeypatch.setattr(vector_store, "query", query)

    hits = await vector_store.rank_summaries(
        7, [0.1, 0.2], [Scope("global", ""), Scope("dev", "")], limit=3,
    )

    sql, params = query.await_args.args
    assert "(scope_type = %s AND scope_id = %s)" in sql
    assert "global" not in params
    assert params[:3] == (7, "dev", "")
    assert hits[0]["ref_key"].startswith("daily:")


@pytest.mark.asyncio
async def test_search_episodic_prepends_semantic_daily_summary(monkeypatch):
    async def fake_embed(texts):
        return [[0.1, 0.2] for _ in texts]

    monkeypatch.setattr(embedder_mod, "get_embedder", lambda: FakeEmbedder())
    monkeypatch.setattr(
        vector_store, "rank_summaries",
        AsyncMock(return_value=[{
            "ref_key": "daily:7:dev::2026-11-20", "kind": "daily",
            "scope_type": "dev", "scope_id": "",
            "text": "决定先修 token 刷新", "updated_at": None,
        }]),
    )
    monkeypatch.setattr(
        episodic_mod, "search_session_summaries", AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        episodic_mod, "search_messages", AsyncMock(return_value=[]),
    )

    hits = await episodic_mod.search_episodic(
        7, "token", [Scope("dev", "")],
    )

    assert hits[0]["kind"] == "daily_summary"
    assert "token" in hits[0]["snippet"]


@pytest.mark.asyncio
async def test_search_episodic_still_works_without_vectors(monkeypatch):
    def broken_embedder():
        raise RuntimeError("no key")

    monkeypatch.setattr(embedder_mod, "get_embedder", broken_embedder)
    monkeypatch.setattr(
        episodic_mod, "search_session_summaries",
        AsyncMock(return_value=[{
            "kind": "session_summary", "session_id": "s", "session_title": "t",
            "snippet": "关键词命中", "created_at": None,
        }]),
    )
    monkeypatch.setattr(
        episodic_mod, "search_messages", AsyncMock(return_value=[]),
    )

    hits = await episodic_mod.search_episodic(7, "关键词", [Scope("dev", "")])

    assert hits[0]["snippet"] == "关键词命中"

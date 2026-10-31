"""Retriever tests: two legs fused by RRF, per-leg degradation."""
import pytest
from unittest.mock import AsyncMock, patch

from app.core.rag.retriever import retrieve
from app.models.domain import RetrievedChunk


def _chunk(cid: str, content: str, score_type: str) -> RetrievedChunk:
    return RetrievedChunk(id=cid, content=content, path="doc.md", score_type=score_type)


@pytest.mark.asyncio
async def test_retrieve_fuses_dense_and_keyword():
    dense = [_chunk("1", "fastapi", "dense"), _chunk("2", "middleware", "dense")]
    keyword = [_chunk("2", "middleware", "keyword"), _chunk("3", "session", "keyword")]

    with patch("app.core.rag.retriever.dense_search", new=AsyncMock(return_value=dense)), \
         patch("app.core.rag.retriever.keyword_search", new=AsyncMock(return_value=keyword)):
        result = await retrieve("FastAPI 中间件", top_k=5, repo_ids=["repo-1"])

    ids = [c.id for c in result]
    # Chunk "2" was returned by both legs, so it must rank first.
    assert ids[0] == "2"
    assert set(ids) == {"1", "2", "3"}


@pytest.mark.asyncio
async def test_retrieve_drops_secret_paths_from_legacy_index():
    dense = [
        RetrievedChunk(id="1", content="SECRET=1", path=".env", score_type="dense"),
        RetrievedChunk(id="2", content="print(1)", path="app.py", score_type="dense"),
    ]
    keyword = [
        RetrievedChunk(id="3", content='{"token": "x"}', path="credentials.json",
                       score_type="keyword"),
    ]

    with patch("app.core.rag.retriever.dense_search", new=AsyncMock(return_value=dense)), \
         patch("app.core.rag.retriever.keyword_search", new=AsyncMock(return_value=keyword)):
        result = await retrieve("token", top_k=5, repo_ids=["repo-1"])

    assert [c.path for c in result] == ["app.py"]


@pytest.mark.asyncio
async def test_retrieve_degrades_when_one_leg_fails():
    keyword = [_chunk("3", "session", "keyword")]

    with patch("app.core.rag.retriever.dense_search", new=AsyncMock(side_effect=RuntimeError("no key"))), \
         patch("app.core.rag.retriever.keyword_search", new=AsyncMock(return_value=keyword)):
        result = await retrieve("session", top_k=5, repo_ids=["repo-1"])

    assert [c.id for c in result] == ["3"]


@pytest.mark.asyncio
async def test_retrieve_returns_empty_when_all_legs_fail():
    with patch("app.core.rag.retriever.dense_search", new=AsyncMock(side_effect=RuntimeError("down"))), \
         patch("app.core.rag.retriever.keyword_search", new=AsyncMock(side_effect=RuntimeError("down"))):
        result = await retrieve("anything", top_k=5, repo_ids=["repo-1"])

    assert result == []


@pytest.mark.asyncio
async def test_retrieve_fails_closed_without_authorized_repos():
    dense = AsyncMock(return_value=[_chunk("1", "leak", "dense")])
    keyword = AsyncMock(return_value=[_chunk("2", "leak", "keyword")])

    with patch("app.core.rag.retriever.dense_search", new=dense), \
         patch("app.core.rag.retriever.keyword_search", new=keyword):
        assert await retrieve("anything", top_k=5, repo_ids=None) == []
        assert await retrieve("anything", top_k=5, repo_ids=[]) == []

    dense.assert_not_awaited()
    keyword.assert_not_awaited()
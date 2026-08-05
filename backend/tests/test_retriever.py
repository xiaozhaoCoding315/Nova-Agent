import pytest
from unittest.mock import AsyncMock, patch
from app.core.rag.retriever import retrieve


@pytest.mark.asyncio
async def test_retrieve_merges_all_three_sources():
    dense_results = [RetrievedChunk(id="d1", content="fastapi", source="doc.md", score_type="dense")]
    keyword_results = [RetrievedChunk(id="k1", content="中间件", source="doc2.md", score_type="keyword")]
    graph_results = [RetrievedChunk(id="g1", content="依赖注入", source="doc3.md", score_type="graph")]

    with patch("app.core.rag.retriever.dense_search", new=AsyncMock(return_value=dense_results)), \
         patch("app.core.rag.retriever.keyword_search", new=AsyncMock(return_value=keyword_results)), \
         patch("app.core.rag.retriever.graph_search", new=AsyncMock(return_value=graph_results)):
        result = await retrieve("FastAPI中间件", top_k=5)
    ids = {c.id for c in result}
    assert "d1" in ids and "k1" in ids and "g1" in ids


from app.models.domain import RetrievedChunk

import pytest
from app.core.rag.retriever import retrieve

@pytest.mark.asyncio
@pytest.mark.integration
async def test_three_way_retrieval_returns_fused_results():
    results = await retrieve("FastAPI中间件", top_k=5)
    assert isinstance(results, list) and len(results) > 0
    assert all(hasattr(r, "score_type") for r in results)

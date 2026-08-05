import pytest
from app.core.evaluation.runner import evaluate_single_query

@pytest.mark.asyncio
@pytest.mark.integration
async def test_full_eval_pipeline():
    result = await evaluate_single_query("FastAPI中间件", relevant_ids=None, mode="all")
    assert "answer" in result
    assert "ragas_scores" in result
    assert len(result["ragas_scores"]) == 4

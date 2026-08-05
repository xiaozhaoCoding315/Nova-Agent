import pytest
from app.core.evaluation.ragas import evaluate_generation

@pytest.mark.asyncio
async def test_ragas_returns_four_dimensions():
    scores = await evaluate_generation(
        "FastAPI是什么", "FastAPI是一个现代Python Web框架",
        "FastAPI是一个高性能的Python Web框架，基于Starlette和Pydantic。")
    for key in ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]:
        assert key in scores and 0.0 <= scores[key] <= 1.0

@pytest.mark.asyncio
async def test_ragas_good_vs_bad():
    good = await evaluate_generation("FastAPI是什么",
        "FastAPI是一个现代Python Web框架，基于Starlette和Pydantic构建。",
        "FastAPI是一个高性能的Python Web框架，基于Starlette和Pydantic。它支持异步编程。")
    bad = await evaluate_generation("FastAPI是什么",
        "FastAPI是Java生态中最流行的框架，由Spring团队开发。",
        "FastAPI是一个高性能的Python Web框架，基于Starlette和Pydantic。")
    assert good["faithfulness"] > bad["faithfulness"]

@pytest.mark.asyncio
async def test_ragas_empty_input():
    scores = await evaluate_generation("", "", "")
    assert isinstance(scores, dict) and len(scores) == 4

import pytest
from app.core.evaluation.metrics import evaluate_retrieval, recall_at_k, mrr, ndcg_at_k, hit_rate


def test_recall_at_k_basic():
    retrieved = ["a", "b", "c"]
    relevant = ["a", "c", "d"]
    assert recall_at_k(retrieved, relevant, 3) == pytest.approx(2/3)


def test_mrr_first_hit():
    retrieved = ["a", "b", "c"]
    relevant = ["a"]
    assert mrr(retrieved, relevant) == 1.0


def test_mrr_second_hit():
    retrieved = ["x", "a", "c"]
    relevant = ["a"]
    assert mrr(retrieved, relevant) == pytest.approx(1/2)


def test_mrr_no_hit():
    retrieved = ["x", "y"]
    relevant = ["a"]
    assert mrr(retrieved, relevant) == 0.0


def test_ndcg_perfect():
    retrieved = ["a", "b", "c"]
    relevant = ["a", "b", "c"]
    assert ndcg_at_k(retrieved, relevant, 3) == pytest.approx(1.0, abs=0.01)


def test_hit_rate_hit():
    retrieved = ["a", "b"]
    relevant = ["b", "c"]
    assert hit_rate(retrieved, relevant, 2) == 1.0


def test_hit_rate_miss():
    retrieved = ["x", "y"]
    relevant = ["a", "b"]
    assert hit_rate(retrieved, relevant, 2) == 0.0


def test_evaluate_retrieval_full():
    retrieved = ["a", "b", "c", "x", "y"]
    relevant = ["a", "c", "z"]
    result = evaluate_retrieval(retrieved, relevant, k_values=[1, 3, 5])
    assert "recall@1" in result
    assert "recall@3" in result
    assert "ndcg@5" in result
    assert "mrr" in result
    assert result["recall@1"] == pytest.approx(1/3)
    assert result["recall@3"] == pytest.approx(2/3)

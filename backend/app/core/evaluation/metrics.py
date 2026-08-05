"""Retrieval evaluation metrics: Recall@K, MRR, NDCG@K, HitRate."""
from typing import Optional


def recall_at_k(retrieved: list, relevant: list, k: int) -> float:
    """Proportion of relevant items found in top-k results."""
    if not relevant:
        return 0.0
    retrieved_k = retrieved[:k]
    hits = sum(1 for r in retrieved_k if r in relevant)
    return hits / len(relevant)


def mrr(retrieved: list, relevant: list) -> float:
    """Mean Reciprocal Rank: 1/rank of first relevant item."""
    for i, item in enumerate(retrieved):
        if item in relevant:
            return 1.0 / (i + 1)
    return 0.0


def dcg_at_k(retrieved: list, relevant: list, k: int) -> float:
    """Discounted Cumulative Gain."""
    dcg = 0.0
    for i, item in enumerate(retrieved[:k]):
        if item in relevant:
            dcg += 1.0 / (i + 1 if i == 0 else (i + 1))
    return dcg


def ndcg_at_k(retrieved: list, relevant: list, k: int) -> float:
    """Normalized DCG."""
    dcg = dcg_at_k(retrieved, relevant, k)
    ideal = dcg_at_k(relevant, relevant, k)
    return dcg / ideal if ideal > 0 else 0.0


def hit_rate(retrieved: list, relevant: list, k: int) -> float:
    """Binary: at least one relevant item in top-k."""
    retrieved_k = set(r[:50] for r in retrieved[:k])  # compare by content prefix
    for rel in relevant:
        if rel[:50] in retrieved_k:
            return 1.0
    return 0.0


def evaluate_retrieval(
    retrieved_ids: list,
    relevant_ids: list,
    k_values: list = None
) -> dict:
    """Run all metrics at multiple K values."""
    if k_values is None:
        k_values = [1, 3, 5, 10]

    results = {}
    for k in k_values:
        results[f"recall@{k}"] = recall_at_k(retrieved_ids, relevant_ids, k)
        results[f"ndcg@{k}"] = ndcg_at_k(retrieved_ids, relevant_ids, k)
        results[f"hit_rate@{k}"] = hit_rate(retrieved_ids, relevant_ids, k)
    results["mrr"] = mrr(retrieved_ids, relevant_ids)
    return results

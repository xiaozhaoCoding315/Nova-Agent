from app.models.domain import RetrievedChunk


def rrf_fuse(
    lists: list[list[RetrievedChunk]],
    k: int = 10,
    top_n: int = 5,
) -> list[RetrievedChunk]:
    """Reciprocal Rank Fusion merges multiple ranked result lists.

    k=10 gives better score differentiation than k=60 (less dilution).
    Scores are normalized to 0.0-1.0 where the top result = 1.0.
    """
    scores: dict[str, float] = {}
    chunk_map: dict[str, RetrievedChunk] = {}

    for ranked_list in lists:
        for rank, chunk in enumerate(ranked_list):
            if chunk.id not in scores:
                scores[chunk.id] = 0.0
                chunk_map[chunk.id] = chunk
            scores[chunk.id] += 1.0 / (k + rank + 1)

    sorted_ids = sorted(scores, key=lambda x: scores[x], reverse=True)

    # Normalize scores to 0.0 - 1.0 for display (max score → 1.0)
    max_score = max(scores.values()) if scores else 1.0

    result = []
    for cid in sorted_ids[:top_n]:
        chunk = chunk_map[cid]
        chunk.score = scores[cid] / max_score if max_score > 0 else 0.0
        result.append(chunk)
    return result

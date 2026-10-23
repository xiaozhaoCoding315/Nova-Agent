"""Reciprocal Rank Fusion with source attribution."""
from app.models.domain import RetrievedChunk


def rrf_fuse(
    lists: list[list[RetrievedChunk]],
    k: int = 10,
    top_n: int = 5,
) -> list[RetrievedChunk]:
    """Merge ranked lists; a chunk found by multiple legs is labeled with all
    contributing sources (e.g. ``dense+keyword``) so fusion is visible."""
    scores: dict[str, float] = {}
    chunk_map: dict[str, RetrievedChunk] = {}
    sources: dict[str, set[str]] = {}

    for ranked_list in lists:
        for rank, chunk in enumerate(ranked_list):
            if chunk.id not in scores:
                scores[chunk.id] = 0.0
                chunk_map[chunk.id] = chunk
                sources[chunk.id] = set()
            scores[chunk.id] += 1.0 / (k + rank + 1)
            if chunk.score_type:
                sources[chunk.id].add(chunk.score_type)

    sorted_ids = sorted(scores, key=lambda x: scores[x], reverse=True)
    max_score = max(scores.values()) if scores else 1.0

    result = []
    for cid in sorted_ids[:top_n]:
        chunk = chunk_map[cid]
        chunk.score = scores[cid] / max_score if max_score > 0 else 0.0
        ordered = [s for s in ("dense", "keyword") if s in sources[cid]]
        if ordered:
            chunk.score_type = "+".join(ordered)
        result.append(chunk)
    return result

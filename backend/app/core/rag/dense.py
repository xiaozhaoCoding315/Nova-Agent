"""Dense retrieval over indexed repo chunks (Qdrant)."""
import asyncio

import structlog

from app.config import settings
from app.core.embedding.embedder import get_embedder
from app.models.domain import RetrievedChunk

logger = structlog.get_logger()


async def dense_search(
    query: str,
    top_k: int = 10,
    repo_ids: list[str] | None = None,
) -> list[RetrievedChunk]:
    from app.db.qdrant import get_client, repo_filter

    vector = (await get_embedder().embed([query]))[0]
    client = get_client()
    resp = await asyncio.to_thread(
        client.query_points,
        settings.qdrant_collection,
        query=vector,
        limit=top_k,
        query_filter=repo_filter(repo_ids),
        with_payload=True,
    )
    points = resp.points if hasattr(resp, "points") else resp.result.points

    results = []
    for r in points:
        payload = r.payload or {}
        results.append(
            RetrievedChunk(
                id=str(r.id),
                content=payload.get("content", ""),
                path=payload.get("path", ""),
                line_start=payload.get("line_start", 0),
                line_end=payload.get("line_end", 0),
                lang=payload.get("lang", ""),
                kind=payload.get("kind", "code"),
                score_type="dense",
                score=r.score or 0.0,
                metadata=payload,
            )
        )
    return results
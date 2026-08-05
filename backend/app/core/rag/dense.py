from qdrant_client import QdrantClient
from app.config import settings
from app.models.domain import RetrievedChunk
from app.core.embedding.embedder import get_embedder

_client = QdrantClient(url=settings.qdrant_url)
_embedder = get_embedder()


async def dense_search(query: str, top_k: int = 10) -> list[RetrievedChunk]:
    vector = (await _embedder.embed([query]))[0]
    from qdrant_client.models import ScoredPoint
    resp = _client.query_points(
        collection_name="novatech_docs",
        query=vector,
        limit=top_k,
        with_payload=True,
    )
    points = resp.points if hasattr(resp, 'points') else resp.result.points
    return [
        RetrievedChunk(
            id=str(r.id),
            content=(r.payload or {}).get("content", ""),
            source=(r.payload or {}).get("source", ""),
            score_type="dense",
            score=r.score or 0.0,
            metadata=r.payload or {},
        )
        for r in points
    ]

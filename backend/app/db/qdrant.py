"""Qdrant client factory + collection management (dense vector store)."""
import asyncio

from qdrant_client import QdrantClient
from qdrant_client.http.exceptions import UnexpectedResponse
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchAny,
    MatchValue,
    PointStruct,
    VectorParams,
)

from app.config import settings

_client: QdrantClient | None = None


def get_client() -> QdrantClient:
    global _client
    if _client is None:
        _client = QdrantClient(url=settings.qdrant_url, timeout=15)
    return _client


def repo_filter(repo_ids: list[str] | None, user_id: int | None = None) -> Filter | None:
    """Filter by repo ids, optionally also by owner for defense in depth."""
    if not repo_ids:
        return None
    must = [FieldCondition(key="repo_id", match=MatchAny(any=repo_ids))]
    if user_id is not None:
        must.append(FieldCondition(key="user_id", match=MatchValue(value=user_id)))
    return Filter(must=must)


async def ensure_collection() -> str:
    """Create the chunks collection if missing. Returns created | already_exists."""
    client = get_client()

    def _run() -> str:
        try:
            client.get_collection(settings.qdrant_collection)
            return "already_exists"
        except UnexpectedResponse as exc:
            if getattr(exc, "status_code", None) != 404:
                raise
        client.create_collection(
            collection_name=settings.qdrant_collection,
            vectors_config=VectorParams(size=settings.embedding_dim, distance=Distance.COSINE),
        )
        return "created"

    return await asyncio.to_thread(_run)


async def upsert_points(points: list[PointStruct]) -> None:
    if not points:
        return
    client = get_client()
    await asyncio.to_thread(client.upsert, settings.qdrant_collection, points=points)


async def backfill_repo_user_payload(repo_id: str, user_id: int) -> None:
    client = get_client()
    await asyncio.to_thread(
        client.set_payload,
        collection_name=settings.qdrant_collection,
        payload={"user_id": user_id},
        points=repo_filter([repo_id]),
    )


async def delete_repo_points(repo_id: str) -> None:
    """Remove all vectors of one repo by payload filter."""
    client = get_client()
    from qdrant_client.models import FilterSelector

    await asyncio.to_thread(
        client.delete,
        settings.qdrant_collection,
        points_selector=FilterSelector(filter=repo_filter([repo_id])),
    )


async def count_points() -> int:
    client = get_client()
    result = await asyncio.to_thread(client.count, settings.qdrant_collection, exact=True)
    return result.count
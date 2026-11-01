"""Two-way retrieval (dense + keyword) fused with RRF, harness-protected.

Each leg degrades independently: a failed leg contributes an empty list and
the other leg still serves the request.
"""
import asyncio

import structlog

from app.config import settings
from app.core.harness.config import TIMEOUTS
from app.core.harness.runtime import execute_with_harness
from app.core.rag.dense import dense_search
from app.core.rag.keyword import keyword_search
from app.core.rag.rrf import rrf_fuse
from app.core.security.paths import is_secret_path
from app.models.domain import RetrievedChunk

logger = structlog.get_logger()


async def retrieve(
    query: str,
    top_k: int = 10,
    repo_ids: list[str] | None = None,
    user_id: int | None = None,
) -> list[RetrievedChunk]:
    # Fail closed: retrieval is always scoped to explicitly authorized repos,
    # and (when known) additionally filtered by owner at the storage layer.
    if not repo_ids:
        return []
    # Without embeddings (local runtime) dense retrieval cannot serve results;
    # only run it when the deployment actually has a vector store.
    legs: list[tuple[str, object]] = [("keyword", keyword_search)]
    if settings.use_embeddings:
        legs.insert(0, ("dense", dense_search))
    results = await asyncio.gather(*[
        execute_with_harness(
            func,
            query,
            top_k,
            repo_ids,
            user_id,
            context=f"retrieval/{name}",
            timeout=TIMEOUTS.retrieval_timeout,
            use_retry=True,
            fallback=lambda *a, **kw: [],
        )
        for name, func in legs
    ])

    valid_lists = [r for r in results if isinstance(r, list) and r]
    if not valid_lists:
        return []
    fused = rrf_fuse(valid_lists, top_n=min(5, top_k))
    # Indexes created before the secret filter may still contain credentials;
    # filtering here prevents leaking them until the repo is re-indexed.
    return [hit for hit in fused if not is_secret_path(hit.path)]
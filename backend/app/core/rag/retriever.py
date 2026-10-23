"""Two-way retrieval (dense + keyword) fused with RRF, harness-protected.

Each leg degrades independently: a failed leg contributes an empty list and
the other leg still serves the request.
"""
import asyncio

import structlog

from app.core.harness.config import TIMEOUTS
from app.core.harness.runtime import execute_with_harness
from app.core.rag.dense import dense_search
from app.core.rag.keyword import keyword_search
from app.core.rag.rrf import rrf_fuse
from app.models.domain import RetrievedChunk

logger = structlog.get_logger()


async def retrieve(
    query: str,
    top_k: int = 10,
    repo_ids: list[str] | None = None,
) -> list[RetrievedChunk]:
    legs = [
        ("dense", dense_search),
        ("keyword", keyword_search),
    ]
    results = await asyncio.gather(*[
        execute_with_harness(
            func,
            query,
            top_k,
            repo_ids,
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
    return rrf_fuse(valid_lists, top_n=min(5, top_k))
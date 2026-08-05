import asyncio
import structlog
from app.models.domain import RetrievedChunk
from app.core.rag.dense import dense_search
from app.core.rag.keyword import keyword_search
from app.core.rag.graph import graph_search
from app.core.rag.rrf import rrf_fuse
from app.core.harness.runtime import execute_with_harness
from app.core.harness.config import TIMEOUTS

logger = structlog.get_logger()


async def retrieve(query: str, top_k: int = 10) -> list[RetrievedChunk]:
    """Parallel three-way retrieval with Harness protection + RRF fusion."""
    tasks = [
        {"func": dense_search, "args": (query, top_k), "kwargs": {},
         "name": "dense", "timeout": TIMEOUTS.retrieval_timeout, "fallback_result": []},
        {"func": keyword_search, "args": (query, top_k), "kwargs": {},
         "name": "keyword", "timeout": TIMEOUTS.retrieval_timeout, "fallback_result": []},
        {"func": graph_search, "args": (query, top_k), "kwargs": {},
         "name": "graph", "timeout": TIMEOUTS.retrieval_timeout, "fallback_result": []},
    ]

    results = await asyncio.gather(*[
        execute_with_harness(
            t["func"], *t["args"],
            context=f"retrieval/{t['name']}",
            timeout=t["timeout"],
            use_retry=True,
            fallback=lambda *a, **kw: [],
        ) for t in tasks
    ])

    valid_lists = [r for r in results if isinstance(r, list) and r]
    if not valid_lists:
        return []
    return rrf_fuse(valid_lists, top_n=min(5, top_k))

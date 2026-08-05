import asyncio
import psycopg
from app.config import settings
from app.models.domain import RetrievedChunk
from app.utils.chinese_analyzer import make_tsquery, highlight_match


def _search_sync(dsn: str, tsquery: str, query: str, top_k: int) -> list[tuple]:
    """Synchronous search executed in a thread pool."""
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            if not tsquery:
                cur.execute(
                    "SELECT id, content, source, 0.5 as rank FROM documents WHERE content ILIKE %s ORDER BY rank DESC LIMIT %s",
                    (f"%{query}%", top_k),
                )
            else:
                cur.execute(
                    "SELECT id, content, source, ts_rank(search_vector, to_tsquery('simple', %s)) AS rank FROM documents WHERE search_vector @@ to_tsquery('simple', %s) ORDER BY rank DESC LIMIT %s",
                    (tsquery, tsquery, top_k),
                )
            return cur.fetchall()


async def keyword_search(query: str, top_k: int = 10) -> list[RetrievedChunk]:
    """Full-text search with Chinese segmentation, runs sync PG in thread pool."""
    tsquery = make_tsquery(query)
    rows = await asyncio.to_thread(_search_sync, settings.postgres_dsn, tsquery, query, top_k)
    return [
        RetrievedChunk(
            id=str(r[0]),
            content=highlight_match(r[1], query) if tsquery else r[1][:500],
            source=r[2],
            score_type="keyword",
            score=float(r[3]) if r[3] else 0.0,
        )
        for r in rows
    ]

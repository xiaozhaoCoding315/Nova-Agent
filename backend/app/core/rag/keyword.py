"""Keyword retrieval over indexed chunks: PG full-text (jieba-preprocessed)
with an ILIKE fallback for tokenization edge cases."""
import asyncio

import psycopg

from app.config import settings
from app.models.domain import RetrievedChunk
from app.utils.chinese_analyzer import highlight_match, make_tsquery


def _search_sync(
    dsn: str,
    tsquery: str,
    query: str,
    top_k: int,
    repo_ids: list[str] | None,
) -> list[tuple]:
    repo_clause = ""
    repo_params: list = []
    if repo_ids:
        repo_clause = "AND c.repo_id = ANY(%s::uuid[])"
        repo_params = [repo_ids]

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            if tsquery:
                cur.execute(
                    f"""
                    SELECT c.id, c.content, f.path, c.line_start, c.line_end, c.lang, c.kind,
                           ts_rank(c.tsv, plainto_tsquery('simple', %s)) AS rank
                    FROM chunks c JOIN repo_files f ON f.id = c.file_id
                    WHERE c.tsv @@ plainto_tsquery('simple', %s) {repo_clause}
                    ORDER BY rank DESC LIMIT %s
                    """,
                    (tsquery, tsquery, *repo_params, top_k),
                )
            else:
                cur.execute(
                    f"""
                    SELECT c.id, c.content, f.path, c.line_start, c.line_end, c.lang, c.kind,
                           0.5 AS rank
                    FROM chunks c JOIN repo_files f ON f.id = c.file_id
                    WHERE c.content ILIKE %s {repo_clause}
                    ORDER BY rank DESC LIMIT %s
                    """,
                    (f"%{query}%", *repo_params, top_k),
                )
            return cur.fetchall()


async def keyword_search(
    query: str,
    top_k: int = 10,
    repo_ids: list[str] | None = None,
) -> list[RetrievedChunk]:
    if not repo_ids:
        return []
    tsquery = make_tsquery(query)
    rows = await asyncio.to_thread(
        _search_sync, settings.postgres_dsn, tsquery, query, top_k, repo_ids
    )
    return [
        RetrievedChunk(
            id=str(r[0]),
            content=highlight_match(r[1], query) if tsquery else r[1][:500],
            path=r[2] or "",
            line_start=r[3] or 0,
            line_end=r[4] or 0,
            lang=r[5] or "",
            kind=r[6] or "code",
            score_type="keyword",
            score=float(r[7]) if r[7] else 0.0,
        )
        for r in rows
    ]
"""Optional pgvector index for long-term facts.

Every deployment does not ship the ``vector`` extension.  Nova probes it
during database init: when present, fact recall and indexing use cosine
distance in PostgreSQL; otherwise callers keep the JSONB cosine fallback.
"""
import json

import structlog

from app.config import settings
from app.core.memory import scope as scope_mod
from app.db import execute, query

logger = structlog.get_logger()

_ENABLED: bool | None = None


def _vector_literal(embedding: list[float]) -> str:
    return json.dumps([float(value) for value in embedding])


def _scope_sql(scopes: list[scope_mod.Scope] | None) -> tuple[str, list]:
    if scopes is None:
        return "", []
    if not scopes:
        return " AND FALSE", []
    parts: list[str] = []
    params: list = []
    for scope in scopes:
        parts.append("(f.scope_type = %s AND f.scope_id = %s)")
        params.extend([scope.type, scope.id])
    return " AND (" + " OR ".join(parts) + ")", params


async def ensure_schema() -> bool:
    """Probe/create pgvector storage; failures leave the fallback in place."""
    global _ENABLED
    try:
        existing = await query(
            "SELECT 1 FROM pg_extension WHERE extname = 'vector' LIMIT 1"
        )
        if not existing:
            await execute("CREATE EXTENSION IF NOT EXISTS vector")
    except Exception as exc:  # noqa: BLE001
        logger.warning("pgvector_unavailable", error=str(exc))
        _ENABLED = False
        return False

    dim = max(1, int(settings.embedding_dim))
    try:
        await execute(
            "CREATE TABLE IF NOT EXISTS fact_vectors ("
            "  fact_id BIGINT PRIMARY KEY REFERENCES facts(id) ON DELETE CASCADE,"
            "  user_id INT NOT NULL,"
            f"  embedding vector({dim}) NOT NULL,"
            "  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()"
            ")"
        )
        try:
            await execute(
                "CREATE INDEX IF NOT EXISTS idx_fact_vectors_hnsw "
                "ON fact_vectors USING hnsw (embedding vector_cosine_ops)"
            )
        except Exception as exc:  # noqa: BLE001 - old pgvector lacks HNSW
            logger.info("pgvector_hnsw_unavailable", error=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.warning("pgvector_schema_failed", error=str(exc))
        _ENABLED = False
        return False

    _ENABLED = True
    return True


async def index_fact(
    fact_id: int, user_id: int, embedding: list[float] | None
) -> None:
    if _ENABLED is not True or not embedding:
        return
    try:
        await execute(
            "INSERT INTO fact_vectors (fact_id, user_id, embedding) "
            "VALUES (%s, %s, %s::vector) ON CONFLICT (fact_id) DO UPDATE SET "
            "embedding = EXCLUDED.embedding, user_id = EXCLUDED.user_id, "
            "updated_at = now()",
            (fact_id, user_id, _vector_literal(embedding)),
        )
    except Exception as exc:  # noqa: BLE001 - indexing must not break writes
        logger.debug("fact_vector_index_failed", fact_id=fact_id, error=str(exc))


async def rank_fact_ids(
    user_id: int,
    embedding: list[float] | None,
    scopes: list[scope_mod.Scope] | None,
    limit: int,
) -> list[int] | None:
    """Return fact ids by cosine distance, or ``None`` when pgvector is off."""
    if _ENABLED is not True or not embedding:
        return None
    scope_sql, scope_params = _scope_sql(scopes)
    try:
        rows = await query(
            "SELECT fv.fact_id FROM fact_vectors fv "
            "JOIN facts f ON f.id = fv.fact_id "
            "WHERE f.user_id = %s AND f.status = 'active' "
            f"{scope_sql} ORDER BY fv.embedding <=> %s::vector LIMIT %s",
            (
                user_id, *scope_params, _vector_literal(embedding),
                max(1, int(limit)),
            ),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("fact_vector_rank_failed", error=str(exc))
        return None
    return [int(row[0]) for row in rows]


async def backfill(limit: int = 200) -> int:
    """Index active facts that predate the pgvector table."""
    if _ENABLED is not True:
        return 0
    try:
        rows = await query(
            "SELECT f.id, f.user_id, f.embedding FROM facts f "
            "LEFT JOIN fact_vectors v ON v.fact_id = f.id "
            "WHERE v.fact_id IS NULL AND f.embedding IS NOT NULL "
            "AND f.status = 'active' LIMIT %s",
            (max(1, int(limit)),),
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("fact_vector_backfill_scan_failed", error=str(exc))
        return 0
    indexed = 0
    for fact_id, user_id, stored in rows:
        try:
            embedding = stored if isinstance(stored, list) else json.loads(stored)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(embedding, list):
            await index_fact(int(fact_id), int(user_id), embedding)
            indexed += 1
    return indexed

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

    try:
        await execute(
            "CREATE TABLE IF NOT EXISTS summary_vectors ("
            "  ref_key VARCHAR(200) PRIMARY KEY,"
            "  user_id INT NOT NULL,"
            "  kind VARCHAR(16) NOT NULL,"
            "  scope_type VARCHAR(24) NOT NULL DEFAULT 'dev',"
            "  scope_id VARCHAR(64) NOT NULL DEFAULT '',"
            "  text TEXT NOT NULL,"
            f"  embedding vector({dim}) NOT NULL,"
            "  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()"
            ")"
        )
        try:
            await execute(
                "CREATE INDEX IF NOT EXISTS idx_summary_vectors_hnsw "
                "ON summary_vectors USING hnsw (embedding vector_cosine_ops)"
            )
        except Exception as exc:  # noqa: BLE001
            logger.info("pgvector_summary_hnsw_unavailable", error=str(exc))
        await execute(
            "CREATE INDEX IF NOT EXISTS idx_summary_vectors_user "
            "ON summary_vectors (user_id, kind, scope_type, scope_id)"
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("pgvector_summary_schema_failed", error=str(exc))
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


# ---------------------------------------------------------------------------
# Summary vectors (daily + session summaries)
# ---------------------------------------------------------------------------

def _summary_scope_sql(scopes: list[scope_mod.Scope] | None) -> tuple[str, list]:
    if scopes is None:
        return "", []
    if not scopes:
        return " AND FALSE", []
    parts: list[str] = []
    params: list = []
    for scope in scopes:
        if scope.type == scope_mod.GLOBAL:
            continue
        parts.append("(scope_type = %s AND scope_id = %s)")
        params.extend([scope.type, scope.id])
    if not parts:
        return " AND FALSE", []
    return " AND (" + " OR ".join(parts) + ")", params


async def _embed_one(text: str) -> list[float] | None:
    try:
        from app.core.embedding.embedder import get_embedder

        return (await get_embedder().embed([text[:4000]]))[0]
    except Exception as exc:  # noqa: BLE001 — vectors are optional
        logger.debug("summary_embedding_failed", error=str(exc))
        return None


async def index_summary(
    ref_key: str,
    user_id: int,
    kind: str,
    scope_type: str,
    scope_id: str,
    text: str,
) -> bool:
    """Embed and upsert one summary; returns False when vectors are off."""
    if _ENABLED is not True or not (text or "").strip():
        return False
    embedding = await _embed_one(text)
    if not embedding:
        return False
    try:
        await execute(
            "INSERT INTO summary_vectors "
            "(ref_key, user_id, kind, scope_type, scope_id, text, embedding) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s::vector) "
            "ON CONFLICT (ref_key) DO UPDATE SET user_id = EXCLUDED.user_id, "
            "kind = EXCLUDED.kind, scope_type = EXCLUDED.scope_type, "
            "scope_id = EXCLUDED.scope_id, text = EXCLUDED.text, "
            "embedding = EXCLUDED.embedding, updated_at = now()",
            (
                ref_key, user_id, kind, scope_type, scope_id, text,
                _vector_literal(embedding),
            ),
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.debug("summary_vector_index_failed", ref=ref_key, error=str(exc))
        return False


async def index_daily(
    user_id: int, scope_type: str, scope_id: str, day, text: str,
) -> bool:
    return await index_summary(
        f"daily:{user_id}:{scope_type}:{scope_id}:{day}",
        user_id, "daily", scope_type, scope_id, text,
    )


async def index_session(
    user_id: int, session_id: str, text: str,
) -> bool:
    """Index a rolling session summary under its session's product scope."""
    if _ENABLED is not True or not (text or "").strip():
        return False
    scope_type, scope_id = scope_mod.DEV, ""
    try:
        rows = await query(
            "SELECT s.product_mode, COALESCE(s.thesis_project_id::text, ''), "
            "(SELECT COUNT(*) FROM session_repos sr WHERE sr.session_id = s.id), "
            "(SELECT sr.repo_id::text FROM session_repos sr "
            " WHERE sr.session_id = s.id LIMIT 1) "
            "FROM sessions s WHERE s.id = %s AND s.user_id = %s",
            (session_id, user_id),
        )
        if rows:
            mode = (rows[0][0] or scope_mod.DEV).strip().lower()
            if mode == scope_mod.THESIS and rows[0][1]:
                scope_type, scope_id = scope_mod.THESIS, str(rows[0][1])
            elif mode == scope_mod.DEV and int(rows[0][2] or 0) == 1 and rows[0][3]:
                scope_type, scope_id = scope_mod.REPO, str(rows[0][3])
    except Exception as exc:  # noqa: BLE001
        logger.debug("summary_session_scope_failed", error=str(exc))
    return await index_summary(
        f"session:{session_id}", user_id, "session",
        scope_type, scope_id, text,
    )


async def delete_summary(ref_key: str) -> None:
    if _ENABLED is not True:
        return
    try:
        await execute(
            "DELETE FROM summary_vectors WHERE ref_key = %s", (ref_key,),
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("summary_vector_delete_failed", ref=ref_key, error=str(exc))


async def delete_user_summaries(user_id: int) -> None:
    if _ENABLED is not True:
        return
    try:
        await execute(
            "DELETE FROM summary_vectors WHERE user_id = %s", (user_id,),
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("summary_vector_purge_failed", error=str(exc))


async def rank_summaries(
    user_id: int,
    embedding: list[float] | None,
    scopes: list[scope_mod.Scope] | None,
    limit: int,
    kind: str | None = None,
) -> list[dict] | None:
    """Semantic summary hits, or ``None`` when pgvector/embeddings are off."""
    if _ENABLED is not True or not embedding:
        return None
    scope_sql, scope_params = _summary_scope_sql(scopes)
    kind_sql = ""
    kind_params: list = []
    if kind:
        kind_sql = " AND kind = %s"
        kind_params = [kind]
    try:
        rows = await query(
            "SELECT ref_key, kind, scope_type, scope_id, text, updated_at "
            "FROM summary_vectors WHERE user_id = %s "
            f"{scope_sql}{kind_sql} "
            "ORDER BY embedding <=> %s::vector LIMIT %s",
            (
                user_id, *scope_params, *kind_params,
                _vector_literal(embedding), max(1, int(limit)),
            ),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("summary_vector_rank_failed", error=str(exc))
        return None
    return [
        {
            "ref_key": row[0], "kind": row[1], "scope_type": row[2],
            "scope_id": row[3] or "", "text": row[4] or "",
            "updated_at": row[5],
        }
        for row in rows
    ]


async def delete_daily_scope(user_id: int, scope_type: str, scope_id: str) -> None:
    if _ENABLED is not True:
        return
    try:
        await execute(
            "DELETE FROM summary_vectors WHERE user_id = %s AND kind = 'daily' "
            "AND scope_type = %s AND scope_id = %s",
            (user_id, scope_type, scope_id),
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("summary_vector_scope_delete_failed", error=str(exc))

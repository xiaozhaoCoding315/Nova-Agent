"""One-click database initialization — idempotent, safe to re-run.

Provides init_postgres(), init_qdrant(), init_neo4j(), check_connectivity(),
and init_all() to bring every backing store to the expected baseline schema.
"""
import asyncio

import psycopg
from qdrant_client import QdrantClient
from qdrant_client.http.exceptions import UnexpectedResponse
from qdrant_client.models import VectorParams, Distance

from app.config import settings
from app.db import transaction
from app.db.neo4j import init_graph

# ---------------------------------------------------------------------------
# PostgreSQL
# ---------------------------------------------------------------------------

# DDL kept as plain strings so it is easy to review and runs transactionally.
# Every statement is idempotent (IF NOT EXISTS / CREATE OR REPLACE / DROP
# TRIGGER IF EXISTS) which makes the whole batch safe to run repeatedly.
_DDL = [
    """
    CREATE TABLE IF NOT EXISTS documents (
        id UUID PRIMARY KEY,
        content TEXT NOT NULL,
        source VARCHAR(500),
        metadata JSONB,
        search_vector tsvector,
        created_at TIMESTAMPTZ DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS agent_facts (
        id UUID PRIMARY KEY,
        session_id VARCHAR(100),
        fact VARCHAR(500) NOT NULL,
        category VARCHAR(50),
        importance FLOAT,
        created_at TIMESTAMPTZ DEFAULT now(),
        last_accessed TIMESTAMPTZ
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS eval_queries (
        id SERIAL PRIMARY KEY,
        query TEXT NOT NULL,
        category VARCHAR(100),
        relevant_ids JSONB,
        notes TEXT,
        created_at TIMESTAMPTZ DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS eval_results (
        id SERIAL PRIMARY KEY,
        run_name VARCHAR(200),
        eval_type VARCHAR(50),
        query_id INT REFERENCES eval_queries(id),
        metrics JSONB,
        ragas_scores JSONB,
        answer TEXT,
        duration_ms FLOAT,
        created_at TIMESTAMPTZ DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS eval_corpora (
        id SERIAL PRIMARY KEY,
        name VARCHAR(200) UNIQUE,
        description TEXT,
        created_at TIMESTAMPTZ DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS audit_log (
        id VARCHAR(20) PRIMARY KEY,
        action VARCHAR(50),
        user_id VARCHAR(100),
        details JSONB DEFAULT '{}',
        risk_level VARCHAR(20),
        created_at TIMESTAMPTZ DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log (action)",
    "CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log (created_at)",
    """
    CREATE OR REPLACE FUNCTION documents_search_vector_update()
    RETURNS trigger AS $$
    BEGIN
        NEW.search_vector := to_tsvector('simple', COALESCE(NEW.content, ''));
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """,
    "DROP TRIGGER IF EXISTS documents_search_vector_trigger ON documents",
    """
    CREATE TRIGGER documents_search_vector_trigger
        BEFORE INSERT OR UPDATE ON documents
        FOR EACH ROW EXECUTE FUNCTION documents_search_vector_update()
    """,
    "CREATE INDEX IF NOT EXISTS idx_documents_search ON documents USING GIN (search_vector)",
    "CREATE INDEX IF NOT EXISTS idx_agent_facts_ttl ON agent_facts (created_at)",
    "CREATE INDEX IF NOT EXISTS idx_agent_facts_session ON agent_facts (session_id)",
    """
    CREATE TABLE IF NOT EXISTS chat_sessions (
        id VARCHAR(64) PRIMARY KEY,
        created_at TIMESTAMPTZ DEFAULT now(),
        updated_at TIMESTAMPTZ DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS chat_messages (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        session_id VARCHAR(64),
        role VARCHAR(20),
        content TEXT,
        created_at TIMESTAMPTZ DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_chat_messages_session ON chat_messages (session_id, created_at)",
    """
    CREATE TABLE IF NOT EXISTS task_states (
        id VARCHAR(64) PRIMARY KEY,
        name VARCHAR(500),
        status VARCHAR(30),
        result JSONB,
        error TEXT,
        created_at TIMESTAMPTZ,
        started_at TIMESTAMPTZ,
        completed_at TIMESTAMPTZ,
        retries INT DEFAULT 0,
        max_retries INT DEFAULT 2,
        parent_id VARCHAR(64),
        children_ids JSONB DEFAULT '[]',
        metadata JSONB DEFAULT '{}',
        history JSONB DEFAULT '[]'
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_task_states_status ON task_states (status, created_at)",
]


async def init_postgres() -> str:
    """Create PostgreSQL tables, triggers, and indexes.

    Returns "already_exists" if the ``documents`` table was present before
    running, otherwise "created".
    """
    existed = await _table_exists("documents")

    # transaction() runs the whole DDL batch in a single connection/transaction.
    await transaction([(sql, None) for sql in _DDL])

    return "already_exists" if existed else "created"


async def _table_exists(table: str) -> bool:
    """Check whether a table already exists in the public schema."""
    from app.db import query
    rows = await query(
        "SELECT EXISTS("
        "  SELECT 1 FROM pg_tables "
        "  WHERE schemaname='public' AND tablename=%s"
        ")",
        (table,),
    )
    return bool(rows and rows[0][0])


# ---------------------------------------------------------------------------
# Qdrant
# ---------------------------------------------------------------------------

async def init_qdrant() -> str:
    """Create the ``novatech_docs`` collection if it does not exist.

    Returns "already_exists" or "created".
    """
    client = QdrantClient(url=settings.qdrant_url)
    try:
        client.get_collection("novatech_docs")
        return "already_exists"
    except UnexpectedResponse as exc:
        # Only a 404 ("collection not found") should fall through to create.
        # Any other status (e.g. 500) or exception type is a real failure —
        # let it propagate so the user sees a clear connection/server error
        # instead of a confusing failure on the create path.
        # Use getattr so non-HTTP errors (no status_code) don't raise AttributeError.
        if getattr(exc, 'status_code', None) != 404:
            raise

    client.create_collection(
        collection_name="novatech_docs",
        vectors_config=VectorParams(size=1024, distance=Distance.COSINE),
    )
    return "created"


# ---------------------------------------------------------------------------
# Neo4j
# ---------------------------------------------------------------------------

async def init_neo4j() -> str:
    """Create Neo4j constraints and indexes. Returns "ok"."""
    await init_graph()
    return "ok"


# ---------------------------------------------------------------------------
# Connectivity + orchestration
# ---------------------------------------------------------------------------

async def check_connectivity() -> dict:
    """Return connection status for all three backing stores.

    Each value is "connected" on success or "failed: <message>" on error.
    """
    status: dict = {}

    # PostgreSQL
    try:
        with psycopg.connect(settings.postgres_dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        status["postgres"] = "connected"
    except Exception as exc:  # noqa: BLE001
        status["postgres"] = f"failed: {exc}"

    # Qdrant
    try:
        client = QdrantClient(url=settings.qdrant_url)
        client.get_collections()
        status["qdrant"] = "connected"
    except Exception as exc:  # noqa: BLE001
        status["qdrant"] = f"failed: {exc}"

    # Neo4j
    try:
        from app.db.neo4j import get_driver
        driver = get_driver()
        with driver.session(database="neo4j") as session:
            session.run("RETURN 1").single()
        status["neo4j"] = "connected"
    except Exception as exc:  # noqa: BLE001
        status["neo4j"] = f"failed: {exc}"

    return status


async def init_all() -> dict:
    """Run connectivity check and all initializers. Returns a status dict."""
    return {
        "connectivity": await check_connectivity(),
        "postgres": await init_postgres(),
        "qdrant": await init_qdrant(),
        "neo4j": await init_neo4j(),
    }


if __name__ == "__main__":
    import sys
    if "--check" in sys.argv:
        result = asyncio.run(check_connectivity())
        for k, v in result.items():
            print(f"  {k}: {v}")
    else:
        asyncio.run(init_all())

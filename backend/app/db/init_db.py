"""Idempotent database initialization — safe to re-run on every boot.

Brings PostgreSQL (schema) and Qdrant (collection) to the baseline the app
expects, and seeds the default admin/demo accounts.
"""
import asyncio

import psycopg
import structlog

from app.config import settings
from app.db import transaction

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# PostgreSQL
# ---------------------------------------------------------------------------

_DDL = [
    """
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        username VARCHAR(64) UNIQUE NOT NULL,
        password_hash VARCHAR(200) NOT NULL,
        role VARCHAR(16) NOT NULL DEFAULT 'demo',
        created_at TIMESTAMPTZ DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sessions (
        id UUID PRIMARY KEY,
        user_id INT REFERENCES users(id) ON DELETE CASCADE,
        title VARCHAR(200) DEFAULT '新对话',
        summary TEXT,
        created_at TIMESTAMPTZ DEFAULT now(),
        updated_at TIMESTAMPTZ DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions (user_id, updated_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS messages (
        id BIGSERIAL PRIMARY KEY,
        session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
        role VARCHAR(16) NOT NULL,
        content TEXT DEFAULT '',
        tool_json JSONB,
        prompt_tokens INT DEFAULT 0,
        completion_tokens INT DEFAULT 0,
        created_at TIMESTAMPTZ DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_messages_session ON messages (session_id, id)",
    """
    CREATE TABLE IF NOT EXISTS facts (
        id BIGSERIAL PRIMARY KEY,
        user_id INT REFERENCES users(id) ON DELETE CASCADE,
        content TEXT NOT NULL,
        hash VARCHAR(64) UNIQUE NOT NULL,
        importance REAL DEFAULT 1.0,
        last_used_at TIMESTAMPTZ DEFAULT now(),
        ttl_days INT DEFAULT 90,
        created_at TIMESTAMPTZ DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_facts_user ON facts (user_id, importance DESC)",
    """
    CREATE TABLE IF NOT EXISTS repos (
        id UUID PRIMARY KEY,
        user_id INT REFERENCES users(id) ON DELETE CASCADE,
        name VARCHAR(200) NOT NULL,
        source VARCHAR(500) DEFAULT '',
        root_path TEXT NOT NULL,
        status VARCHAR(20) DEFAULT 'pending',
        error TEXT,
        stats JSONB DEFAULT '{}',
        created_at TIMESTAMPTZ DEFAULT now(),
        updated_at TIMESTAMPTZ DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_repos_user ON repos (user_id, created_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS repo_files (
        id BIGSERIAL PRIMARY KEY,
        repo_id UUID REFERENCES repos(id) ON DELETE CASCADE,
        path TEXT NOT NULL,
        language VARCHAR(32),
        size INT DEFAULT 0,
        line_count INT DEFAULT 0,
        is_doc BOOLEAN DEFAULT FALSE
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_repo_files_repo ON repo_files (repo_id, path)",
    """
    CREATE TABLE IF NOT EXISTS symbols (
        id BIGSERIAL PRIMARY KEY,
        repo_id UUID REFERENCES repos(id) ON DELETE CASCADE,
        file_id BIGINT REFERENCES repo_files(id) ON DELETE CASCADE,
        kind VARCHAR(20),
        name VARCHAR(200),
        parent VARCHAR(200),
        line_start INT,
        line_end INT,
        signature TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_symbols_repo_name ON symbols (repo_id, name)",
    "CREATE INDEX IF NOT EXISTS idx_symbols_file ON symbols (file_id)",
    """
    CREATE TABLE IF NOT EXISTS chunks (
        id BIGSERIAL PRIMARY KEY,
        repo_id UUID REFERENCES repos(id) ON DELETE CASCADE,
        file_id BIGINT REFERENCES repo_files(id) ON DELETE CASCADE,
        content TEXT NOT NULL,
        line_start INT,
        line_end INT,
        lang VARCHAR(32),
        kind VARCHAR(16) DEFAULT 'code',
        tsv TSVECTOR
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_chunks_repo ON chunks (repo_id)",
    "CREATE INDEX IF NOT EXISTS idx_chunks_tsv ON chunks USING GIN (tsv)",
    """
    CREATE TABLE IF NOT EXISTS usage_log (
        id BIGSERIAL PRIMARY KEY,
        user_id INT,
        session_id UUID,
        model VARCHAR(64),
        prompt_tokens INT DEFAULT 0,
        completion_tokens INT DEFAULT 0,
        tool_calls INT DEFAULT 0,
        created_at TIMESTAMPTZ DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_usage_user_time ON usage_log (user_id, created_at)",
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
    "CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log (user_id, created_at)",
]


async def ensure_database() -> str:
    """Create the target database on first run. Returns created | already_exists."""

    def _run() -> str:
        with psycopg.connect(settings.postgres_admin_dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (settings.postgres_db,))
                if cur.fetchone():
                    return "already_exists"
                # Identifier cannot be parameterized; validate strictly instead.
                db = settings.postgres_db
                if not db.replace("_", "").isalnum():
                    raise ValueError(f"unsafe database name: {db!r}")
                cur.execute(f'CREATE DATABASE "{db}"')
                return "created"

    return await asyncio.to_thread(_run)


async def init_postgres() -> str:
    db_state = await ensure_database()
    await transaction([(sql, None) for sql in _DDL])
    return db_state


# ---------------------------------------------------------------------------
# Qdrant
# ---------------------------------------------------------------------------

async def init_qdrant() -> str:
    from app.db.qdrant import ensure_collection
    return await ensure_collection()


# ---------------------------------------------------------------------------
# Connectivity + orchestration
# ---------------------------------------------------------------------------

async def check_connectivity() -> dict:
    status: dict = {}

    try:
        with psycopg.connect(settings.postgres_dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        status["postgres"] = "connected"
    except Exception as exc:  # noqa: BLE001
        status["postgres"] = f"failed: {exc}"

    try:
        from qdrant_client import QdrantClient
        client = QdrantClient(url=settings.qdrant_url, timeout=5)
        client.get_collections()
        status["qdrant"] = "connected"
    except Exception as exc:  # noqa: BLE001
        status["qdrant"] = f"failed: {exc}"

    return status


async def init_all() -> dict:
    result = {"connectivity": await check_connectivity()}
    if not str(result["connectivity"].get("postgres", "")).startswith("connected"):
        logger.error("postgres_unreachable_skipping_init", detail=result["connectivity"]["postgres"])
        return result

    result["postgres"] = await init_postgres()

    try:
        result["qdrant"] = await init_qdrant()
    except Exception as exc:  # noqa: BLE001
        result["qdrant"] = f"failed: {exc}"
        logger.error("qdrant_init_failed", error=str(exc))

    try:
        from app.core.security.auth import ensure_default_users
        result["users"] = await ensure_default_users()
    except Exception as exc:  # noqa: BLE001
        result["users"] = f"failed: {exc}"
        logger.error("user_seed_failed", error=str(exc))

    return result


if __name__ == "__main__":
    import sys

    if "--check" in sys.argv:
        for k, v in asyncio.run(check_connectivity()).items():
            print(f"  {k}: {v}")
    else:
        for k, v in asyncio.run(init_all()).items():
            print(f"  {k}: {v}")
"""Idempotent database initialization — safe to re-run on every boot.

Brings PostgreSQL (schema) and Qdrant (collection) to the baseline the app
expects, and seeds the default admin/demo accounts.

The DDL below is the *baseline* for a fresh database.  Schema changes for
existing databases live in ``_MIGRATIONS`` and are recorded in
``schema_migrations``.  New columns must go through a migration; do not keep
appending one-off ALTER statements to the baseline forever.
"""
import asyncio

import psycopg
import structlog

from app.config import settings
from app.db import query, transaction

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# PostgreSQL
# ---------------------------------------------------------------------------

# Baseline schema, ordered so that every foreign-key target exists before the
# table that references it.  Keep this list topologically sorted.
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
    CREATE TABLE IF NOT EXISTS user_llm_settings (
        user_id INT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
        provider VARCHAR(32) NOT NULL,
        base_url TEXT NOT NULL,
        model VARCHAR(120) NOT NULL,
        api_key_enc TEXT NOT NULL,
        updated_at TIMESTAMPTZ DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sessions (
        id UUID PRIMARY KEY,
        user_id INT REFERENCES users(id) ON DELETE CASCADE,
        title VARCHAR(200) DEFAULT '新对话',
        summary TEXT,
        summary_upto_id BIGINT DEFAULT 0,
        permission_mode VARCHAR(12) DEFAULT 'ask',
        repo_ids JSONB DEFAULT '[]'::jsonb,
        model VARCHAR(120),
        created_at TIMESTAMPTZ DEFAULT now(),
        updated_at TIMESTAMPTZ DEFAULT now()
    )
    """,
    "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS permission_mode VARCHAR(12) DEFAULT 'ask'",
    "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS repo_ids JSONB DEFAULT '[]'::jsonb",
    "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS summary_upto_id BIGINT DEFAULT 0",
    "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS model VARCHAR(120)",
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
    CREATE TABLE IF NOT EXISTS repos (
        id UUID PRIMARY KEY,
        user_id INT REFERENCES users(id) ON DELETE CASCADE,
        name VARCHAR(200) NOT NULL,
        source VARCHAR(500) DEFAULT '',
        root_path TEXT NOT NULL,
        status VARCHAR(20) DEFAULT 'pending',
        error TEXT,
        stats JSONB DEFAULT '{}',
        stack_mode VARCHAR(20) DEFAULT 'python',
        created_at TIMESTAMPTZ DEFAULT now(),
        updated_at TIMESTAMPTZ DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_repos_user ON repos (user_id, created_at DESC)",
    "ALTER TABLE repos ADD COLUMN IF NOT EXISTS brain JSONB DEFAULT '{}'::jsonb",
    "ALTER TABLE repos ADD COLUMN IF NOT EXISTS kind VARCHAR(16) DEFAULT 'import'",
    "ALTER TABLE repos ADD COLUMN IF NOT EXISTS stack_mode VARCHAR(20) DEFAULT 'python'",
    "ALTER TABLE repos ADD COLUMN IF NOT EXISTS brief TEXT",
    "ALTER TABLE repos ADD COLUMN IF NOT EXISTS rules TEXT",
    "ALTER TABLE repos ADD COLUMN IF NOT EXISTS plan JSONB",
    "ALTER TABLE repos ADD COLUMN IF NOT EXISTS proposal JSONB",
    "ALTER TABLE repos ADD COLUMN IF NOT EXISTS last_check JSONB",
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
    CREATE TABLE IF NOT EXISTS file_deps (
        id BIGSERIAL PRIMARY KEY,
        repo_id UUID REFERENCES repos(id) ON DELETE CASCADE,
        file_id BIGINT REFERENCES repo_files(id) ON DELETE CASCADE,
        source_path TEXT NOT NULL,
        target TEXT NOT NULL,
        resolved_path TEXT,
        kind VARCHAR(16)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_file_deps_repo ON file_deps (repo_id)",
    "CREATE INDEX IF NOT EXISTS idx_file_deps_resolved ON file_deps (repo_id, resolved_path)",
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
    CREATE TABLE IF NOT EXISTS edits (
        id UUID PRIMARY KEY,
        user_id INT REFERENCES users(id) ON DELETE CASCADE,
        session_id UUID REFERENCES sessions(id) ON DELETE SET NULL,
        repo_id UUID REFERENCES repos(id) ON DELETE CASCADE,
        status VARCHAR(12) DEFAULT 'pending',
        files JSONB NOT NULL,
        base_files JSONB,
        diff TEXT,
        note TEXT,
        review JSONB,
        created_at TIMESTAMPTZ DEFAULT now(),
        applied_at TIMESTAMPTZ
    )
    """,
    "ALTER TABLE edits ADD COLUMN IF NOT EXISTS review JSONB",
    "CREATE INDEX IF NOT EXISTS idx_edits_repo ON edits (repo_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_edits_user ON edits (user_id, created_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS trace_events (
        id BIGSERIAL PRIMARY KEY,
        session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
        turn_id UUID,
        kind VARCHAR(32),
        payload JSONB,
        created_at TIMESTAMPTZ DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_trace_session ON trace_events (session_id, id)",
    "CREATE INDEX IF NOT EXISTS idx_trace_turn ON trace_events (turn_id)",
    """
    CREATE TABLE IF NOT EXISTS facts (
        id BIGSERIAL PRIMARY KEY,
        user_id INT REFERENCES users(id) ON DELETE CASCADE,
        content TEXT NOT NULL,
        hash VARCHAR(64) NOT NULL,
        embedding JSONB,
        importance REAL DEFAULT 1.0,
        last_used_at TIMESTAMPTZ DEFAULT now(),
        ttl_days INT DEFAULT 90,
        promoted_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ DEFAULT now()
    )
    """,
    "ALTER TABLE facts ADD COLUMN IF NOT EXISTS embedding JSONB",
    "ALTER TABLE facts ADD COLUMN IF NOT EXISTS promoted_at TIMESTAMPTZ",
    # Older installs declared hash globally UNIQUE, which made identical facts
    # collide across users.  Replace it with a per-user unique index.
    "ALTER TABLE facts DROP CONSTRAINT IF EXISTS facts_hash_key",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_facts_user_hash ON facts (user_id, hash)",
    "CREATE INDEX IF NOT EXISTS idx_facts_user ON facts (user_id, importance DESC)",
    """
    CREATE TABLE IF NOT EXISTS memory_daily (
        user_id INT REFERENCES users(id) ON DELETE CASCADE,
        day DATE NOT NULL,
        summary TEXT NOT NULL,
        message_count INT DEFAULT 0,
        created_at TIMESTAMPTZ DEFAULT now(),
        updated_at TIMESTAMPTZ DEFAULT now(),
        PRIMARY KEY (user_id, day)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_memory_daily_user ON memory_daily (user_id, day DESC)",
    """
    CREATE TABLE IF NOT EXISTS fact_days (
        fact_id BIGINT REFERENCES facts(id) ON DELETE CASCADE,
        day DATE NOT NULL,
        count INT DEFAULT 1,
        PRIMARY KEY (fact_id, day)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_fact_days_day ON fact_days (day)",
    """
    CREATE TABLE IF NOT EXISTS usage_log (
        id BIGSERIAL PRIMARY KEY,
        user_id INT,
        session_id UUID,
        model VARCHAR(64),
        prompt_tokens INT DEFAULT 0,
        completion_tokens INT DEFAULT 0,
        tool_calls INT DEFAULT 0,
        source VARCHAR(20) DEFAULT 'chat',
        created_at TIMESTAMPTZ DEFAULT now()
    )
    """,
    "ALTER TABLE usage_log ADD COLUMN IF NOT EXISTS source VARCHAR(20) DEFAULT 'chat'",
    "CREATE INDEX IF NOT EXISTS idx_usage_user_time ON usage_log (user_id, created_at)",
    """
    CREATE TABLE IF NOT EXISTS jobs (
        id UUID PRIMARY KEY,
        user_id INT REFERENCES users(id) ON DELETE CASCADE,
        kind VARCHAR(32) NOT NULL,
        payload JSONB NOT NULL DEFAULT '{}'::jsonb,
        status VARCHAR(16) NOT NULL DEFAULT 'queued',
        progress REAL DEFAULT 0,
        step TEXT,
        result JSONB,
        error TEXT,
        idempotency_key VARCHAR(200),
        attempts INT DEFAULT 0,
        max_attempts INT DEFAULT 1,
        cancel_requested BOOLEAN DEFAULT FALSE,
        heartbeat_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ DEFAULT now(),
        started_at TIMESTAMPTZ,
        finished_at TIMESTAMPTZ
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs (status, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_jobs_user ON jobs (user_id, created_at DESC)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_idempotency ON jobs (idempotency_key) "
    "WHERE idempotency_key IS NOT NULL",
    """
    CREATE TABLE IF NOT EXISTS tasks (
        id UUID PRIMARY KEY,
        user_id INT REFERENCES users(id) ON DELETE CASCADE,
        repo_id UUID REFERENCES repos(id) ON DELETE CASCADE,
        job_id UUID REFERENCES jobs(id) ON DELETE SET NULL,
        title VARCHAR(200),
        bug_report TEXT NOT NULL,
        status VARCHAR(20) DEFAULT 'running',
        steps JSONB DEFAULT '[]'::jsonb,
        result JSONB DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ DEFAULT now(),
        updated_at TIMESTAMPTZ DEFAULT now()
    )
    """,
    "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS job_id UUID REFERENCES jobs(id) ON DELETE SET NULL",
    "CREATE INDEX IF NOT EXISTS idx_tasks_user ON tasks (user_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_tasks_job ON tasks (job_id)",
    """
    CREATE TABLE IF NOT EXISTS change_requests (
        id UUID PRIMARY KEY,
        user_id INT REFERENCES users(id) ON DELETE CASCADE,
        repo_id UUID REFERENCES repos(id) ON DELETE CASCADE,
        title VARCHAR(200) NOT NULL DEFAULT '变更',
        requirements TEXT NOT NULL DEFAULT '',
        goal TEXT NOT NULL DEFAULT '',
        in_scope JSONB DEFAULT '[]'::jsonb,
        out_scope JSONB DEFAULT '[]'::jsonb,
        interfaces JSONB DEFAULT '[]'::jsonb,
        acceptance_cases JSONB DEFAULT '[]'::jsonb,
        nfr JSONB DEFAULT '[]'::jsonb,
        open_questions JSONB DEFAULT '[]'::jsonb,
        status VARCHAR(24) DEFAULT 'drafting',
        version INT DEFAULT 1,
        plan_notes TEXT,
        proposal JSONB,
        evidence JSONB,
        error TEXT,
        job_id UUID REFERENCES jobs(id) ON DELETE SET NULL,
        approved_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ DEFAULT now(),
        updated_at TIMESTAMPTZ DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_changes_user ON change_requests (user_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_changes_repo ON change_requests (repo_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_changes_job ON change_requests (job_id)",
    """
    CREATE TABLE IF NOT EXISTS change_tasks (
        id UUID PRIMARY KEY,
        request_id UUID REFERENCES change_requests(id) ON DELETE CASCADE,
        repo_id UUID REFERENCES repos(id) ON DELETE CASCADE,
        seq INT NOT NULL,
        title VARCHAR(200) NOT NULL,
        kind VARCHAR(20) NOT NULL,
        in_scope JSONB DEFAULT '[]'::jsonb,
        out_scope JSONB DEFAULT '[]'::jsonb,
        acceptance TEXT NOT NULL,
        depends_on JSONB DEFAULT '[]'::jsonb,
        status VARCHAR(20) DEFAULT 'pending',
        attempts INT DEFAULT 0,
        result JSONB DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ DEFAULT now(),
        updated_at TIMESTAMPTZ DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_change_tasks_request ON change_tasks (request_id, seq)",
    """
    CREATE TABLE IF NOT EXISTS external_actions (
        id UUID PRIMARY KEY,
        user_id INT REFERENCES users(id) ON DELETE CASCADE,
        idempotency_key VARCHAR(240) NOT NULL UNIQUE,
        action VARCHAR(40) NOT NULL,
        target VARCHAR(240),
        status VARCHAR(16) NOT NULL DEFAULT 'pending',
        request JSONB DEFAULT '{}'::jsonb,
        response JSONB DEFAULT '{}'::jsonb,
        error TEXT,
        created_at TIMESTAMPTZ DEFAULT now(),
        updated_at TIMESTAMPTZ DEFAULT now(),
        finished_at TIMESTAMPTZ
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_external_actions_user ON external_actions (user_id, created_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS deployments (
        id UUID PRIMARY KEY,
        user_id INT REFERENCES users(id) ON DELETE CASCADE,
        repo_id UUID REFERENCES repos(id) ON DELETE CASCADE,
        action_id UUID REFERENCES external_actions(id) ON DELETE SET NULL,
        container_name VARCHAR(120),
        host_port INT,
        url VARCHAR(300),
        status VARCHAR(20) NOT NULL DEFAULT 'starting',
        image VARCHAR(120),
        command TEXT,
        workspace_path TEXT,
        error TEXT,
        created_at TIMESTAMPTZ DEFAULT now(),
        updated_at TIMESTAMPTZ DEFAULT now(),
        stopped_at TIMESTAMPTZ
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_deployments_user ON deployments (user_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_deployments_repo ON deployments (repo_id, created_at DESC)",
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

_SCHEMA_MIGRATIONS_DDL = """
    CREATE TABLE IF NOT EXISTS schema_migrations (
        version INT PRIMARY KEY,
        applied_at TIMESTAMPTZ DEFAULT now()
    )
"""

# Incremental migrations for databases created by an older baseline.  Each
# statement must be idempotent: startup may race with a previous partial run.
_MIGRATIONS: list[tuple[int, list[str]]] = [
    (1, [
        "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS summary_upto_id BIGINT DEFAULT 0",
    ]),
    (2, [
        "ALTER TABLE facts ADD COLUMN IF NOT EXISTS embedding JSONB",
        "ALTER TABLE facts DROP CONSTRAINT IF EXISTS facts_hash_key",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_facts_user_hash ON facts (user_id, hash)",
    ]),
    (3, [
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id UUID PRIMARY KEY,
            user_id INT REFERENCES users(id) ON DELETE CASCADE,
            kind VARCHAR(32) NOT NULL,
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            status VARCHAR(16) NOT NULL DEFAULT 'queued',
            progress REAL DEFAULT 0,
            step TEXT,
            result JSONB,
            error TEXT,
            idempotency_key VARCHAR(200),
            attempts INT DEFAULT 0,
            max_attempts INT DEFAULT 1,
            cancel_requested BOOLEAN DEFAULT FALSE,
            heartbeat_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ DEFAULT now(),
            started_at TIMESTAMPTZ,
            finished_at TIMESTAMPTZ
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs (status, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_jobs_user ON jobs (user_id, created_at DESC)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_idempotency ON jobs (idempotency_key) "
        "WHERE idempotency_key IS NOT NULL",
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS job_id UUID REFERENCES jobs(id) ON DELETE SET NULL",
        "CREATE INDEX IF NOT EXISTS idx_tasks_job ON tasks (job_id)",
    ]),
    (4, [
        """
        CREATE TABLE IF NOT EXISTS change_requests (
            id UUID PRIMARY KEY,
            user_id INT REFERENCES users(id) ON DELETE CASCADE,
            repo_id UUID REFERENCES repos(id) ON DELETE CASCADE,
            title VARCHAR(200) NOT NULL DEFAULT '变更',
            requirements TEXT NOT NULL DEFAULT '',
            goal TEXT NOT NULL DEFAULT '',
            in_scope JSONB DEFAULT '[]'::jsonb,
            out_scope JSONB DEFAULT '[]'::jsonb,
            interfaces JSONB DEFAULT '[]'::jsonb,
            acceptance_cases JSONB DEFAULT '[]'::jsonb,
            nfr JSONB DEFAULT '[]'::jsonb,
            open_questions JSONB DEFAULT '[]'::jsonb,
            status VARCHAR(24) DEFAULT 'drafting',
            version INT DEFAULT 1,
            plan_notes TEXT,
            proposal JSONB,
            evidence JSONB,
            error TEXT,
            job_id UUID REFERENCES jobs(id) ON DELETE SET NULL,
            approved_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ DEFAULT now()
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_changes_user ON change_requests (user_id, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_changes_repo ON change_requests (repo_id, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_changes_job ON change_requests (job_id)",
        """
        CREATE TABLE IF NOT EXISTS change_tasks (
            id UUID PRIMARY KEY,
            request_id UUID REFERENCES change_requests(id) ON DELETE CASCADE,
            repo_id UUID REFERENCES repos(id) ON DELETE CASCADE,
            seq INT NOT NULL,
            title VARCHAR(200) NOT NULL,
            kind VARCHAR(20) NOT NULL,
            in_scope JSONB DEFAULT '[]'::jsonb,
            out_scope JSONB DEFAULT '[]'::jsonb,
            acceptance TEXT NOT NULL,
            depends_on JSONB DEFAULT '[]'::jsonb,
            status VARCHAR(20) DEFAULT 'pending',
            attempts INT DEFAULT 0,
            result JSONB DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ DEFAULT now()
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_change_tasks_request ON change_tasks (request_id, seq)",
    ]),
    (5, [
        "ALTER TABLE facts ADD COLUMN IF NOT EXISTS promoted_at TIMESTAMPTZ",
        """
        CREATE TABLE IF NOT EXISTS memory_daily (
            user_id INT REFERENCES users(id) ON DELETE CASCADE,
            day DATE NOT NULL,
            summary TEXT NOT NULL,
            message_count INT DEFAULT 0,
            created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ DEFAULT now(),
            PRIMARY KEY (user_id, day)
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_memory_daily_user ON memory_daily (user_id, day DESC)",
        """
        CREATE TABLE IF NOT EXISTS fact_days (
            fact_id BIGINT REFERENCES facts(id) ON DELETE CASCADE,
            day DATE NOT NULL,
            count INT DEFAULT 1,
            PRIMARY KEY (fact_id, day)
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_fact_days_day ON fact_days (day)",
    ]),
    (6, [
        """
        CREATE TABLE IF NOT EXISTS external_actions (
            id UUID PRIMARY KEY,
            user_id INT REFERENCES users(id) ON DELETE CASCADE,
            idempotency_key VARCHAR(240) NOT NULL UNIQUE,
            action VARCHAR(40) NOT NULL,
            target VARCHAR(240),
            status VARCHAR(16) NOT NULL DEFAULT 'pending',
            request JSONB DEFAULT '{}'::jsonb,
            response JSONB DEFAULT '{}'::jsonb,
            error TEXT,
            created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ DEFAULT now(),
            finished_at TIMESTAMPTZ
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_external_actions_user ON external_actions (user_id, created_at DESC)",
        """
        CREATE TABLE IF NOT EXISTS deployments (
            id UUID PRIMARY KEY,
            user_id INT REFERENCES users(id) ON DELETE CASCADE,
            repo_id UUID REFERENCES repos(id) ON DELETE CASCADE,
            action_id UUID REFERENCES external_actions(id) ON DELETE SET NULL,
            container_name VARCHAR(120),
            host_port INT,
            url VARCHAR(300),
            status VARCHAR(20) NOT NULL DEFAULT 'starting',
            image VARCHAR(120),
            command TEXT,
            workspace_path TEXT,
            error TEXT,
            created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ DEFAULT now(),
            stopped_at TIMESTAMPTZ
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_deployments_user ON deployments (user_id, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_deployments_repo ON deployments (repo_id, created_at DESC)",
    ]),
    (7, [
        "ALTER TABLE repos ADD COLUMN IF NOT EXISTS stack_mode VARCHAR(20) DEFAULT 'python'",
    ]),
    (8, [
        """
        CREATE TABLE IF NOT EXISTS user_llm_settings (
            user_id INT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            provider VARCHAR(32) NOT NULL,
            base_url TEXT NOT NULL,
            model VARCHAR(120) NOT NULL,
            api_key_enc TEXT NOT NULL,
            updated_at TIMESTAMPTZ DEFAULT now()
        )
        """,
        "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS model VARCHAR(120)",
    ]),
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

    # Baseline first: a fresh database gets a complete, correctly ordered
    # schema.  Then record/apply incremental migrations.
    await transaction([(sql, None) for sql in _DDL])
    await transaction([(_SCHEMA_MIGRATIONS_DDL, None)])

    applied = {int(row[0]) for row in await query("SELECT version FROM schema_migrations")}
    for version, statements in _MIGRATIONS:
        if version in applied:
            continue
        await transaction(
            [(sql, None) for sql in statements]
            + [(
                "INSERT INTO schema_migrations (version) VALUES (%s) "
                "ON CONFLICT (version) DO NOTHING",
                (version,),
            )]
        )
        logger.info("schema_migration_applied", version=version)

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

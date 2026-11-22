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
        display_name VARCHAR(80),
        role VARCHAR(16) NOT NULL DEFAULT 'demo',
        status VARCHAR(16) NOT NULL DEFAULT 'active',
        is_guest BOOLEAN NOT NULL DEFAULT FALSE,
        expires_at TIMESTAMPTZ,
        token_version INT NOT NULL DEFAULT 0,
        password_updated_at TIMESTAMPTZ,
        recovery_code_hash VARCHAR(200),
        last_login_at TIMESTAMPTZ,
        quota_daily_tokens INT,
        quota_hourly_messages INT,
        quota_sandbox_daily INT,
        quota_job_hourly INT,
        quota_storage_mb INT,
        self_daily_tokens INT,
        self_hourly_messages INT,
        self_sandbox_daily INT,
        created_at TIMESTAMPTZ DEFAULT now()
    )
    """,
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS display_name VARCHAR(80)",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS status VARCHAR(16) NOT NULL DEFAULT 'active'",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_guest BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS token_version INT NOT NULL DEFAULT 0",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS password_updated_at TIMESTAMPTZ",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS recovery_code_hash VARCHAR(200)",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMPTZ",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS quota_daily_tokens INT",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS quota_hourly_messages INT",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS quota_sandbox_daily INT",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS quota_job_hourly INT",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS quota_storage_mb INT",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS self_daily_tokens INT",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS self_hourly_messages INT",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS self_sandbox_daily INT",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS created_ip VARCHAR(64)",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS email VARCHAR(190)",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified BOOLEAN NOT NULL DEFAULT FALSE",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users (email) WHERE email IS NOT NULL",
    """
    CREATE TABLE IF NOT EXISTS email_codes (
        id SERIAL PRIMARY KEY,
        email VARCHAR(190) NOT NULL,
        code_hash VARCHAR(200) NOT NULL,
        purpose VARCHAR(16) NOT NULL,
        expires_at TIMESTAMPTZ NOT NULL,
        used_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_email_codes_email ON email_codes (email, purpose, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_users_status ON users (status, expires_at)",
    "CREATE INDEX IF NOT EXISTS idx_users_guest_ip ON users (created_ip) WHERE is_guest",
    """
    CREATE TABLE IF NOT EXISTS invite_codes (
        id SERIAL PRIMARY KEY,
        code VARCHAR(32) UNIQUE NOT NULL,
        note VARCHAR(120),
        max_uses INT NOT NULL DEFAULT 1,
        used_count INT NOT NULL DEFAULT 0,
        created_by INT REFERENCES users(id) ON DELETE SET NULL,
        created_at TIMESTAMPTZ DEFAULT now(),
        expires_at TIMESTAMPTZ
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS local_exec_requests (
        id UUID PRIMARY KEY,
        user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        cwd TEXT NOT NULL DEFAULT '.',
        command TEXT NOT NULL,
        status VARCHAR(16) NOT NULL DEFAULT 'pending',
        output TEXT,
        exit_code INT,
        created_at TIMESTAMPTZ DEFAULT now(),
        updated_at TIMESTAMPTZ DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_local_exec_pending ON local_exec_requests (user_id, status, created_at)",
    "ALTER TABLE local_exec_requests ADD COLUMN IF NOT EXISTS kind VARCHAR(12) NOT NULL DEFAULT 'shell'",
    "ALTER TABLE local_exec_requests ADD COLUMN IF NOT EXISTS file_path TEXT",
    "ALTER TABLE local_exec_requests ADD COLUMN IF NOT EXISTS content TEXT",
    """
    CREATE TABLE IF NOT EXISTS local_agent_heartbeats (
        user_id INT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
        last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now()
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
    "ALTER TABLE user_llm_settings ADD COLUMN IF NOT EXISTS context_window INT",
    "ALTER TABLE user_llm_settings ADD COLUMN IF NOT EXISTS reasoning_effort VARCHAR(12)",
    """
    CREATE TABLE IF NOT EXISTS user_llm_providers (
        user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        provider VARCHAR(32) NOT NULL,
        base_url TEXT NOT NULL,
        model VARCHAR(120) NOT NULL,
        api_key_enc TEXT NOT NULL DEFAULT '',
        context_window INT,
        reasoning_effort VARCHAR(12),
        is_default BOOLEAN NOT NULL DEFAULT FALSE,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (user_id, provider)
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_user_llm_default "
    "ON user_llm_providers (user_id) WHERE is_default",
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
        primary_repo_id UUID,
        created_at TIMESTAMPTZ DEFAULT now(),
        updated_at TIMESTAMPTZ DEFAULT now()
    )
    """,
    "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS permission_mode VARCHAR(12) DEFAULT 'ask'",
    "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS repo_ids JSONB DEFAULT '[]'::jsonb",
    "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS summary_upto_id BIGINT DEFAULT 0",
    "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS model VARCHAR(120)",
    "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS primary_repo_id UUID",
    "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS llm_overrides JSONB NOT NULL DEFAULT '{}'::jsonb",
    "CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions (user_id, updated_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS messages (
        id BIGSERIAL PRIMARY KEY,
        session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
        role VARCHAR(16) NOT NULL,
        content TEXT DEFAULT '',
        tool_json JSONB,
        attachments JSONB DEFAULT '[]'::jsonb,
        prompt_tokens INT DEFAULT 0,
        completion_tokens INT DEFAULT 0,
        created_at TIMESTAMPTZ DEFAULT now()
    )
    """,
    "ALTER TABLE messages ADD COLUMN IF NOT EXISTS attachments JSONB DEFAULT '[]'::jsonb",
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
    CREATE TABLE IF NOT EXISTS session_repos (
        session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
        repo_id UUID REFERENCES repos(id) ON DELETE CASCADE,
        created_at TIMESTAMPTZ DEFAULT now(),
        PRIMARY KEY (session_id, repo_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_session_repos_repo ON session_repos (repo_id, session_id)",
    """
    CREATE TABLE IF NOT EXISTS user_files (
        id UUID PRIMARY KEY,
        user_id INT REFERENCES users(id) ON DELETE CASCADE,
        repo_id UUID REFERENCES repos(id) ON DELETE SET NULL,
        session_id UUID REFERENCES sessions(id) ON DELETE SET NULL,
        filename VARCHAR(255) NOT NULL,
        mime VARCHAR(120),
        size BIGINT NOT NULL DEFAULT 0,
        sha256 VARCHAR(64),
        storage_path TEXT NOT NULL,
        purpose VARCHAR(20) DEFAULT 'attachment',
        created_at TIMESTAMPTZ DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_user_files_user ON user_files (user_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_user_files_session ON user_files (session_id)",
    "CREATE INDEX IF NOT EXISTS idx_user_files_repo ON user_files (repo_id)",
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
    "ALTER TABLE repo_files ADD COLUMN IF NOT EXISTS content_hash VARCHAR(64)",
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
        idempotency_key VARCHAR(240) NOT NULL,
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
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_user_idempotency "
        "ON jobs (user_id, idempotency_key)",
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
            idempotency_key VARCHAR(240) NOT NULL,
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
    (9, [
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS display_name VARCHAR(80)",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS status VARCHAR(16) NOT NULL DEFAULT 'active'",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_guest BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS token_version INT NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS password_updated_at TIMESTAMPTZ",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS recovery_code_hash VARCHAR(200)",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMPTZ",
        "UPDATE users SET display_name = username WHERE display_name IS NULL",
        "CREATE INDEX IF NOT EXISTS idx_users_status ON users (status, expires_at)",
    ]),
    (10, [
        "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS primary_repo_id UUID",
        """
        CREATE TABLE IF NOT EXISTS session_repos (
            session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
            repo_id UUID REFERENCES repos(id) ON DELETE CASCADE,
            created_at TIMESTAMPTZ DEFAULT now(),
            PRIMARY KEY (session_id, repo_id)
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_session_repos_repo ON session_repos (repo_id, session_id)",
        """
        DO $$ BEGIN
            ALTER TABLE sessions ADD CONSTRAINT fk_sessions_primary_repo
            FOREIGN KEY (primary_repo_id) REFERENCES repos(id) ON DELETE SET NULL;
        EXCEPTION WHEN duplicate_object THEN NULL; END $$;
        """,
        """
        INSERT INTO session_repos (session_id, repo_id)
        SELECT s.id, r.id
        FROM sessions s
        CROSS JOIN LATERAL jsonb_array_elements_text(COALESCE(s.repo_ids, '[]'::jsonb)) AS elem(value)
        JOIN repos r ON r.id::text = elem.value AND r.user_id = s.user_id
        ON CONFLICT DO NOTHING
        """,
        """
        UPDATE sessions s SET primary_repo_id = sr.repo_id
        FROM (
            SELECT DISTINCT ON (session_id) session_id, repo_id
            FROM session_repos ORDER BY session_id, created_at, repo_id
        ) sr
        WHERE s.id = sr.session_id AND s.primary_repo_id IS NULL
        """,
    ]),
    (11, [
        "ALTER TABLE messages ADD COLUMN IF NOT EXISTS attachments JSONB DEFAULT '[]'::jsonb",
        """
        CREATE TABLE IF NOT EXISTS user_files (
            id UUID PRIMARY KEY,
            user_id INT REFERENCES users(id) ON DELETE CASCADE,
            repo_id UUID REFERENCES repos(id) ON DELETE SET NULL,
            session_id UUID REFERENCES sessions(id) ON DELETE SET NULL,
            filename VARCHAR(255) NOT NULL,
            mime VARCHAR(120),
            size BIGINT NOT NULL DEFAULT 0,
            sha256 VARCHAR(64),
            storage_path TEXT NOT NULL,
            purpose VARCHAR(20) DEFAULT 'attachment',
            created_at TIMESTAMPTZ DEFAULT now()
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_user_files_user ON user_files (user_id, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_user_files_session ON user_files (session_id)",
        "CREATE INDEX IF NOT EXISTS idx_user_files_repo ON user_files (repo_id)",
    ]),
    (12, [
        "DROP INDEX IF EXISTS idx_jobs_idempotency",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_user_idempotency "
        "ON jobs (user_id, idempotency_key)",
        "ALTER TABLE external_actions DROP CONSTRAINT IF EXISTS external_actions_idempotency_key_key",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_external_actions_user_key "
        "ON external_actions (user_id, idempotency_key)",
    ]),
    (13, [
        # Per-user quota overrides (NULL = inherit the role-tier default from
        # env) and self-imposed budgets (applied on top as a lower cap).
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS quota_daily_tokens INT",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS quota_hourly_messages INT",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS quota_sandbox_daily INT",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS quota_job_hourly INT",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS quota_storage_mb INT",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS self_daily_tokens INT",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS self_hourly_messages INT",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS self_sandbox_daily INT",
    ]),
    (14, [
        """
        CREATE TABLE IF NOT EXISTS night_queue (
            id UUID PRIMARY KEY,
            user_id INT REFERENCES users(id) ON DELETE CASCADE,
            kind VARCHAR(20) NOT NULL,
            target_id UUID,
            payload JSONB DEFAULT '{}'::jsonb,
            title VARCHAR(200),
            status VARCHAR(16) NOT NULL DEFAULT 'pending',
            job_id UUID,
            error TEXT,
            created_at TIMESTAMPTZ DEFAULT now(),
            started_at TIMESTAMPTZ,
            finished_at TIMESTAMPTZ
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_night_queue_user ON night_queue (user_id, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_night_queue_status ON night_queue (status, created_at)",
        """
        CREATE TABLE IF NOT EXISTS debt_snapshots (
            id BIGSERIAL PRIMARY KEY,
            repo_id UUID REFERENCES repos(id) ON DELETE CASCADE,
            user_id INT REFERENCES users(id) ON DELETE CASCADE,
            score INT NOT NULL DEFAULT 0,
            metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ DEFAULT now()
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_debt_repo_time ON debt_snapshots (repo_id, created_at DESC)",
    ]),
    (15, [
        """
        CREATE TABLE IF NOT EXISTS lessons (
            id UUID PRIMARY KEY,
            user_id INT REFERENCES users(id) ON DELETE CASCADE,
            repo_id UUID REFERENCES repos(id) ON DELETE CASCADE,
            kind VARCHAR(16) NOT NULL DEFAULT 'practice',
            content TEXT NOT NULL,
            source_type VARCHAR(24) NOT NULL,
            source_id VARCHAR(64) NOT NULL,
            hits INT NOT NULL DEFAULT 0,
            misses INT NOT NULL DEFAULT 0,
            last_hit_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ DEFAULT now()
        )
        """,
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_lessons_source "
        "ON lessons (user_id, source_type, source_id)",
        "CREATE INDEX IF NOT EXISTS idx_lessons_context "
        "ON lessons (user_id, repo_id, hits DESC, updated_at DESC)",
    ]),
    (16, [
        # Builder smoke-boot result (boot container + health check + teardown).
        "ALTER TABLE repos ADD COLUMN IF NOT EXISTS smoke JSONB",
    ]),
    (17, [
        """
        CREATE TABLE IF NOT EXISTS user_llm_providers (
            user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            provider VARCHAR(32) NOT NULL,
            base_url TEXT NOT NULL,
            model VARCHAR(120) NOT NULL,
            api_key_enc TEXT NOT NULL DEFAULT '',
            context_window INT,
            reasoning_effort VARCHAR(12),
            is_default BOOLEAN NOT NULL DEFAULT FALSE,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (user_id, provider)
        )
        """,
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_user_llm_default "
        "ON user_llm_providers (user_id) WHERE is_default",
        """
        INSERT INTO user_llm_providers
            (user_id, provider, base_url, model, api_key_enc,
             context_window, reasoning_effort, is_default)
        SELECT user_id, provider, base_url, model, api_key_enc,
               context_window, reasoning_effort, TRUE
        FROM user_llm_settings
        WHERE provider IN ('dashscope', 'deepseek', 'openai', 'anthropic', 'custom')
        ON CONFLICT (user_id, provider) DO NOTHING
        """,
        "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS llm_overrides JSONB NOT NULL DEFAULT '{}'::jsonb",
    ]),
    (18, [
        "ALTER TABLE repos ADD COLUMN IF NOT EXISTS origin VARCHAR(12) NOT NULL DEFAULT 'upload'",
        "UPDATE repos SET origin = 'git' WHERE source LIKE 'git:%' AND origin = 'upload'",
    ]),
    (19, [
        """
        CREATE TABLE IF NOT EXISTS turns (
            id UUID PRIMARY KEY,
            session_id UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            user_message_id BIGINT,
            assistant_message_id BIGINT,
            job_id UUID REFERENCES jobs(id) ON DELETE SET NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'queued',
            cancel_requested BOOLEAN NOT NULL DEFAULT FALSE,
            error TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            finished_at TIMESTAMPTZ
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_turns_session "
        "ON turns (session_id, created_at DESC)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_turns_one_active ON turns (session_id) "
        "WHERE status IN ('queued', 'running')",
        """
        CREATE TABLE IF NOT EXISTS turn_events (
            id BIGSERIAL PRIMARY KEY,
            turn_id UUID NOT NULL REFERENCES turns(id) ON DELETE CASCADE,
            seq BIGINT NOT NULL,
            type VARCHAR(40) NOT NULL,
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (turn_id, seq)
        )
        """,
    ]),
    (20, [
        """
        CREATE TABLE IF NOT EXISTS thesis_projects (
            id UUID PRIMARY KEY,
            user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title VARCHAR(200) NOT NULL,
            school VARCHAR(120) NOT NULL DEFAULT '',
            degree VARCHAR(24) NOT NULL DEFAULT 'undergraduate',
            template_id VARCHAR(80) NOT NULL DEFAULT 'generic-undergraduate-v1',
            status VARCHAR(24) NOT NULL DEFAULT 'draft',
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_thesis_projects_user "
        "ON thesis_projects (user_id, updated_at DESC)",
        """
        CREATE TABLE IF NOT EXISTS thesis_documents (
            id UUID PRIMARY KEY,
            project_id UUID NOT NULL REFERENCES thesis_projects(id) ON DELETE CASCADE,
            user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            filename VARCHAR(255) NOT NULL,
            storage_path TEXT NOT NULL,
            sha256 VARCHAR(64) NOT NULL,
            size BIGINT NOT NULL DEFAULT 0,
            mime VARCHAR(120) NOT NULL DEFAULT
                'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            status VARCHAR(24) NOT NULL DEFAULT 'uploaded',
            parse_error TEXT,
            document_model JSONB,
            stats JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_thesis_documents_project "
        "ON thesis_documents (project_id, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_thesis_documents_user "
        "ON thesis_documents (user_id, created_at DESC)",
        """
        CREATE TABLE IF NOT EXISTS thesis_issues (
            id UUID PRIMARY KEY,
            project_id UUID NOT NULL REFERENCES thesis_projects(id) ON DELETE CASCADE,
            document_id UUID NOT NULL REFERENCES thesis_documents(id) ON DELETE CASCADE,
            user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            rule_id VARCHAR(80) NOT NULL,
            category VARCHAR(40) NOT NULL,
            severity VARCHAR(16) NOT NULL DEFAULT 'warn',
            title VARCHAR(240) NOT NULL,
            detail TEXT NOT NULL DEFAULT '',
            location JSONB NOT NULL DEFAULT '{}'::jsonb,
            evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
            status VARCHAR(16) NOT NULL DEFAULT 'open',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_thesis_issues_project "
        "ON thesis_issues (project_id, status, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_thesis_issues_document "
        "ON thesis_issues (document_id)",
    ]),
    (21, [
        "ALTER TABLE thesis_documents "
        "ADD COLUMN IF NOT EXISTS working_path TEXT",
        "ALTER TABLE thesis_documents "
        "ADD COLUMN IF NOT EXISTS working_sha256 VARCHAR(64)",
        "ALTER TABLE thesis_documents "
        "ADD COLUMN IF NOT EXISTS version INT NOT NULL DEFAULT 1",
        "ALTER TABLE thesis_issues "
        "ADD COLUMN IF NOT EXISTS fix_type VARCHAR(40)",
        "ALTER TABLE thesis_issues "
        "ADD COLUMN IF NOT EXISTS fix_payload JSONB NOT NULL DEFAULT '{}'::jsonb",
        "ALTER TABLE thesis_issues "
        "ADD COLUMN IF NOT EXISTS source VARCHAR(300) NOT NULL DEFAULT ''",
        "ALTER TABLE thesis_issues "
        "ADD COLUMN IF NOT EXISTS template_version VARCHAR(40) NOT NULL DEFAULT ''",
        "ALTER TABLE thesis_issues "
        "ADD COLUMN IF NOT EXISTS confidence VARCHAR(16) NOT NULL DEFAULT 'high'",
        "ALTER TABLE thesis_issues "
        "ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now()",
        """
        CREATE TABLE IF NOT EXISTS thesis_fixes (
            id UUID PRIMARY KEY,
            project_id UUID NOT NULL REFERENCES thesis_projects(id) ON DELETE CASCADE,
            document_id UUID NOT NULL REFERENCES thesis_documents(id) ON DELETE CASCADE,
            issue_id UUID REFERENCES thesis_issues(id) ON DELETE SET NULL,
            user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            rule_id VARCHAR(80) NOT NULL,
            fix_type VARCHAR(40) NOT NULL,
            before JSONB NOT NULL DEFAULT '{}'::jsonb,
            after JSONB NOT NULL DEFAULT '{}'::jsonb,
            backup_path TEXT NOT NULL DEFAULT '',
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            undone_at TIMESTAMPTZ
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_thesis_fixes_document "
        "ON thesis_fixes (document_id, applied_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_thesis_fixes_project "
        "ON thesis_fixes (project_id, applied_at DESC)",
        """
        CREATE TABLE IF NOT EXISTS thesis_citations (
            id UUID PRIMARY KEY,
            project_id UUID NOT NULL REFERENCES thesis_projects(id) ON DELETE CASCADE,
            document_id UUID NOT NULL REFERENCES thesis_documents(id) ON DELETE CASCADE,
            user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            kind VARCHAR(16) NOT NULL,
            raw VARCHAR(500) NOT NULL DEFAULT '',
            normalized JSONB NOT NULL DEFAULT '{}'::jsonb,
            status VARCHAR(32) NOT NULL DEFAULT 'unverified',
            confidence VARCHAR(16) NOT NULL DEFAULT 'medium',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_thesis_citations_project "
        "ON thesis_citations (project_id, kind)",
        """
        CREATE TABLE IF NOT EXISTS thesis_disclosures (
            id UUID PRIMARY KEY,
            project_id UUID NOT NULL REFERENCES thesis_projects(id) ON DELETE CASCADE,
            user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            tool VARCHAR(120) NOT NULL DEFAULT '',
            tool_version VARCHAR(40) NOT NULL DEFAULT '',
            purpose TEXT NOT NULL DEFAULT '',
            stage VARCHAR(80) NOT NULL DEFAULT '',
            prompt TEXT NOT NULL DEFAULT '',
            output TEXT NOT NULL DEFAULT '',
            modified BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_thesis_disclosures_project "
        "ON thesis_disclosures (project_id, created_at DESC)",
    ]),
    (22, [
        "ALTER TABLE thesis_citations "
        "ADD COLUMN IF NOT EXISTS doi TEXT",
        "ALTER TABLE thesis_citations "
        "ADD COLUMN IF NOT EXISTS metadata_status VARCHAR(24) NOT NULL DEFAULT ''",
        "ALTER TABLE thesis_citations "
        "ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb",
        "ALTER TABLE thesis_citations "
        "ADD COLUMN IF NOT EXISTS metadata_fetched_at TIMESTAMPTZ",
        """
        CREATE TABLE IF NOT EXISTS thesis_metadata_cache (
            doi TEXT PRIMARY KEY,
            status VARCHAR(24) NOT NULL DEFAULT 'ok',
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            fetched_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS thesis_reference_pdfs (
            id UUID PRIMARY KEY,
            project_id UUID NOT NULL REFERENCES thesis_projects(id) ON DELETE CASCADE,
            user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            filename VARCHAR(200) NOT NULL,
            sha256 VARCHAR(64) NOT NULL,
            size BIGINT NOT NULL DEFAULT 0,
            page_count INT NOT NULL DEFAULT 0,
            storage_path TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_thesis_reference_pdfs_project "
        "ON thesis_reference_pdfs (project_id, created_at DESC)",
        """
        CREATE TABLE IF NOT EXISTS thesis_citation_evidence (
            id UUID PRIMARY KEY,
            project_id UUID NOT NULL REFERENCES thesis_projects(id) ON DELETE CASCADE,
            document_id UUID REFERENCES thesis_documents(id) ON DELETE CASCADE,
            user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            reference_index INT,
            reference_raw VARCHAR(500) NOT NULL DEFAULT '',
            pdf_id UUID REFERENCES thesis_reference_pdfs(id) ON DELETE CASCADE,
            page INT,
            quote TEXT NOT NULL DEFAULT '',
            score DOUBLE PRECISION NOT NULL DEFAULT 0,
            method VARCHAR(16) NOT NULL DEFAULT '',
            support VARCHAR(24) NOT NULL DEFAULT 'needs_review',
            note TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_thesis_citation_evidence_project "
        "ON thesis_citation_evidence (project_id, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_thesis_citation_evidence_reference "
        "ON thesis_citation_evidence (project_id, reference_index)",
    ]),
    # 23: thesis chat sessions and the optional engineering project they sit on.
    (23, [
        "ALTER TABLE sessions "
        "ADD COLUMN IF NOT EXISTS product_mode VARCHAR(16) NOT NULL DEFAULT 'dev'",
        "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS thesis_project_id UUID",
        "CREATE INDEX IF NOT EXISTS idx_sessions_product "
        "ON sessions (user_id, product_mode, updated_at DESC)",
        "ALTER TABLE thesis_projects ADD COLUMN IF NOT EXISTS source_repo_id UUID",
        "ALTER TABLE thesis_projects "
        "ADD COLUMN IF NOT EXISTS source_notes TEXT NOT NULL DEFAULT ''",
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'sessions_thesis_project_fk'
            ) THEN
                ALTER TABLE sessions ADD CONSTRAINT sessions_thesis_project_fk
                    FOREIGN KEY (thesis_project_id)
                    REFERENCES thesis_projects(id) ON DELETE SET NULL;
            END IF;
        END $$;
        """,
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'thesis_projects_source_repo_fk'
            ) THEN
                ALTER TABLE thesis_projects ADD CONSTRAINT thesis_projects_source_repo_fk
                    FOREIGN KEY (source_repo_id)
                    REFERENCES repos(id) ON DELETE SET NULL;
            END IF;
        END $$;
        """,
    ]),
    # 24: thesis FK indexes, constraint checks and orphaned thesis sessions.
    (24, [
        "CREATE INDEX IF NOT EXISTS idx_sessions_thesis_project "
        "ON sessions (thesis_project_id)",
        "CREATE INDEX IF NOT EXISTS idx_thesis_projects_source_repo "
        "ON thesis_projects (source_repo_id)",
        "CREATE INDEX IF NOT EXISTS idx_thesis_issues_user "
        "ON thesis_issues (user_id, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_thesis_fixes_issue "
        "ON thesis_fixes (issue_id)",
        "CREATE INDEX IF NOT EXISTS idx_thesis_fixes_user "
        "ON thesis_fixes (user_id, applied_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_thesis_citations_document "
        "ON thesis_citations (document_id)",
        "CREATE INDEX IF NOT EXISTS idx_thesis_citations_user "
        "ON thesis_citations (user_id, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_thesis_disclosures_user "
        "ON thesis_disclosures (user_id, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_thesis_reference_pdfs_user "
        "ON thesis_reference_pdfs (user_id, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_thesis_citation_evidence_pdf "
        "ON thesis_citation_evidence (pdf_id)",
        "CREATE INDEX IF NOT EXISTS idx_thesis_citation_evidence_document "
        "ON thesis_citation_evidence (document_id)",
        # A project's chat must not outlive the project as a thesis session
        # without a project; reset those rows so they cannot open broken chats.
        "UPDATE sessions SET product_mode = 'dev', thesis_project_id = NULL "
        "WHERE product_mode = 'thesis' AND thesis_project_id IS NULL",
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'sessions_product_mode_check'
            ) THEN
                ALTER TABLE sessions ADD CONSTRAINT sessions_product_mode_check
                    CHECK (product_mode IN ('dev', 'thesis')) NOT VALID;
            END IF;
        END $$;
        """,
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'thesis_documents_status_check'
            ) THEN
                ALTER TABLE thesis_documents ADD CONSTRAINT thesis_documents_status_check
                    CHECK (status IN ('uploaded', 'parsed', 'failed')) NOT VALID;
            END IF;
        END $$;
        """,
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'thesis_issues_severity_check'
            ) THEN
                ALTER TABLE thesis_issues ADD CONSTRAINT thesis_issues_severity_check
                    CHECK (severity IN ('info', 'warn', 'blocker')) NOT VALID;
            END IF;
        END $$;
        """,
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'thesis_issues_status_check'
            ) THEN
                ALTER TABLE thesis_issues ADD CONSTRAINT thesis_issues_status_check
                    CHECK (status IN ('open', 'ignored', 'fixed')) NOT VALID;
            END IF;
        END $$;
        """,
    ]),
    # 25: thesis stage machine (M3).  Stage state is one JSON document per
    # project; events are append-only so a confirmation can always be traced
    # back to the transition that produced it.
    (25, [
        "ALTER TABLE thesis_projects "
        "ADD COLUMN IF NOT EXISTS stage_state JSONB NOT NULL DEFAULT '{}'::jsonb",
        """
        CREATE TABLE IF NOT EXISTS thesis_stage_events (
            id UUID PRIMARY KEY,
            project_id UUID NOT NULL REFERENCES thesis_projects(id) ON DELETE CASCADE,
            user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            event_type VARCHAR(24) NOT NULL,
            stage VARCHAR(24) NOT NULL,
            from_stage VARCHAR(24) NOT NULL DEFAULT '',
            readiness VARCHAR(24) NOT NULL DEFAULT '',
            content_sha VARCHAR(64) NOT NULL DEFAULT '',
            note TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_thesis_stage_events_project "
        "ON thesis_stage_events (project_id, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_thesis_stage_events_user "
        "ON thesis_stage_events (user_id, created_at DESC)",
    ]),
    # 26: GitHub delivery (M2).  The token is encrypted with the same helper
    # as provider keys; pull-request rows exist only for PRs Nova created, so
    # the review loop always has a local, auditable record of the authorization.
    (26, [
        """
        CREATE TABLE IF NOT EXISTS user_github_connections (
            user_id INT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            login VARCHAR(80) NOT NULL DEFAULT '',
            token_enc TEXT NOT NULL,
            scopes TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS github_pull_requests (
            id UUID PRIMARY KEY,
            user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            repo_id UUID REFERENCES repos(id) ON DELETE CASCADE,
            owner VARCHAR(120) NOT NULL DEFAULT '',
            repo VARCHAR(120) NOT NULL DEFAULT '',
            number INT NOT NULL,
            url TEXT NOT NULL DEFAULT '',
            title VARCHAR(300) NOT NULL DEFAULT '',
            head VARCHAR(200) NOT NULL DEFAULT '',
            base VARCHAR(200) NOT NULL DEFAULT '',
            draft BOOLEAN NOT NULL DEFAULT TRUE,
            state VARCHAR(20) NOT NULL DEFAULT 'open',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (repo_id, number)
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_github_prs_user "
        "ON github_pull_requests (user_id, created_at DESC)",
    ]),
    # 27: memory isolation + recoverable compaction.  Facts and daily
    # summaries carry an explicit scope so dev, thesis-project and repo
    # memories cannot leak into each other.  Existing rows become global.
    (27, [
        "ALTER TABLE facts ADD COLUMN IF NOT EXISTS scope_type VARCHAR(24) NOT NULL DEFAULT 'global'",
        "ALTER TABLE facts ADD COLUMN IF NOT EXISTS scope_id VARCHAR(64) NOT NULL DEFAULT ''",
        "ALTER TABLE facts ADD COLUMN IF NOT EXISTS source_session_id UUID "
        "REFERENCES sessions(id) ON DELETE SET NULL",
        "ALTER TABLE facts ADD COLUMN IF NOT EXISTS source_message_id BIGINT",
        "ALTER TABLE facts ADD COLUMN IF NOT EXISTS confidence REAL DEFAULT 1.0",
        "ALTER TABLE facts ADD COLUMN IF NOT EXISTS last_decayed_at DATE NOT NULL DEFAULT CURRENT_DATE",
        # Before scopes existed, thesis extraction was disabled, so every old
        # fact came from dev conversations.  Keep them out of thesis recall.
        "UPDATE facts SET scope_type = 'dev' WHERE scope_type = 'global' AND scope_id = ''",
        "DROP INDEX IF EXISTS idx_facts_user_hash",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_facts_scope_hash "
        "ON facts (user_id, scope_type, scope_id, hash)",
        "CREATE INDEX IF NOT EXISTS idx_facts_scope "
        "ON facts (user_id, scope_type, scope_id, importance DESC)",
        "ALTER TABLE memory_daily ADD COLUMN IF NOT EXISTS scope_type "
        "VARCHAR(24) NOT NULL DEFAULT 'dev'",
        "ALTER TABLE memory_daily ADD COLUMN IF NOT EXISTS scope_id "
        "VARCHAR(64) NOT NULL DEFAULT ''",
        # The old primary key (user_id, day) would reject a second scope on the
        # same day; replace it with a scope-aware unique index.
        "ALTER TABLE memory_daily DROP CONSTRAINT IF EXISTS memory_daily_pkey",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_daily_scope "
        "ON memory_daily (user_id, scope_type, scope_id, day)",
        "CREATE INDEX IF NOT EXISTS idx_memory_daily_user_scope "
        "ON memory_daily (user_id, scope_type, scope_id, day DESC)",
        """
        CREATE TABLE IF NOT EXISTS compaction_records (
            id BIGSERIAL PRIMARY KEY,
            session_id UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            turn_id UUID,
            summary TEXT NOT NULL,
            message_count INT NOT NULL DEFAULT 0,
            tokens_before INT NOT NULL DEFAULT 0,
            tokens_after INT NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_compaction_session "
        "ON compaction_records (session_id, created_at DESC)",
        # Retryable jobs become claimable only after their backoff expires.
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS available_at "
        "TIMESTAMPTZ NOT NULL DEFAULT now()",
    ]),
    # 28: fact lifecycle.  Categories let cross-project preferences live in
    # global scope; status/version/supersedes keep corrections visible instead
    # of silently deleting the old value.  pgvector storage is created at
    # runtime by ``vector_store.ensure_schema`` because not every deployment
    # ships the extension.
    (28, [
        "ALTER TABLE facts ADD COLUMN IF NOT EXISTS category "
        "VARCHAR(24) NOT NULL DEFAULT 'fact'",
        "ALTER TABLE facts ADD COLUMN IF NOT EXISTS status "
        "VARCHAR(16) NOT NULL DEFAULT 'active'",
        "ALTER TABLE facts ADD COLUMN IF NOT EXISTS version INT NOT NULL DEFAULT 1",
        "ALTER TABLE facts ADD COLUMN IF NOT EXISTS supersedes_id BIGINT "
        "REFERENCES facts(id) ON DELETE SET NULL",
        "ALTER TABLE facts ADD COLUMN IF NOT EXISTS updated_at "
        "TIMESTAMPTZ NOT NULL DEFAULT now()",
        "CREATE INDEX IF NOT EXISTS idx_facts_scope_status "
        "ON facts (user_id, scope_type, scope_id, status, importance DESC)",
    ]),
]


LATEST_SCHEMA_VERSION = _MIGRATIONS[-1][0] if _MIGRATIONS else 0


def _target_dbname() -> str:
    """Database the app actually connects to — an override DSN wins."""
    if settings.postgres_dsn_override:
        from psycopg.conninfo import conninfo_to_dict

        override = conninfo_to_dict(settings.postgres_dsn_override)
        return override.get("dbname") or settings.postgres_db
    return settings.postgres_db


async def ensure_database() -> str:
    """Create the target database on first run. Returns created | already_exists."""

    def _run() -> str:
        db = _target_dbname()
        with psycopg.connect(settings.postgres_admin_dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db,))
                if cur.fetchone():
                    return "already_exists"
                # Identifier cannot be parameterized; validate strictly instead.
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

    # pgvector is optional; a missing extension must never block startup.
    try:
        from app.core.memory import vector_store
        await vector_store.ensure_schema()
    except Exception as exc:  # noqa: BLE001
        logger.warning("fact_vector_schema_skipped", error=str(exc))

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

    if not settings.use_embeddings:
        status["qdrant"] = "skipped: embeddings disabled"
        return status

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

    if settings.is_local:
        result["storage"] = "skipped: local mode"
    else:
        # Imported lazily: user_storage imports app.db, which imports this
        # module, so a module-level import would be circular.
        try:
            from app.core.storage.user_storage import migrate_legacy_repos

            result["storage"] = await migrate_legacy_repos()
        except Exception as exc:  # noqa: BLE001
            result["storage"] = f"failed: {exc}"
            logger.error("repo_storage_migration_failed", error=str(exc))

    if not settings.use_embeddings:
        result["qdrant"] = "skipped: embeddings disabled"
        result["qdrant_payload"] = "skipped: embeddings disabled"
    else:
        try:
            result["qdrant"] = await init_qdrant()
        except Exception as exc:  # noqa: BLE001
            result["qdrant"] = f"failed: {exc}"
            logger.error("qdrant_init_failed", error=str(exc))

        try:
            from app.db.qdrant import backfill_repo_user_payload
            repos = await query("SELECT id, user_id FROM repos")
            for repo_id, user_id in repos:
                await backfill_repo_user_payload(str(repo_id), int(user_id))
            result["qdrant_payload"] = len(repos)
        except Exception as exc:  # noqa: BLE001
            result["qdrant_payload"] = f"failed: {exc}"
            logger.warning("qdrant_payload_backfill_failed", error=str(exc))

    if settings.is_local:
        try:
            from app.core.security.auth import ensure_local_user
            user = await ensure_local_user()
            result["users"] = f"local: {user['username']}"
        except Exception as exc:  # noqa: BLE001
            result["users"] = f"failed: {exc}"
            logger.error("local_user_seed_failed", error=str(exc))
    else:
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

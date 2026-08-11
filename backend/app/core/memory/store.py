"""Cross-session memory: persist facts and conversation summaries to PostgreSQL."""
import asyncio
from datetime import datetime, timedelta
from app.db import query, execute, transaction

# TTL configuration (in days)
TTL_DAYS = {
    "general": 30,
    "learning": 90,
    "preference": 365,
    "domain": 365,
    "style": 180,
}


async def _ensure_table():
    await transaction([
        (
            """
            CREATE TABLE IF NOT EXISTS agent_facts (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                session_id VARCHAR(100),
                fact VARCHAR(500) NOT NULL,
                category VARCHAR(50) DEFAULT 'general',
                importance FLOAT DEFAULT 0.5,
                created_at TIMESTAMPTZ DEFAULT now(),
                last_accessed TIMESTAMPTZ DEFAULT now()
            )
            """,
            (),
        ),
        (
            "CREATE INDEX IF NOT EXISTS idx_agent_facts_ttl ON agent_facts (created_at)",
            (),
        ),
        (
            "CREATE INDEX IF NOT EXISTS idx_agent_facts_session ON agent_facts (session_id)",
            (),
        ),
    ])


async def save_fact(session_id: str, fact: str, category: str = "general", importance: float = 0.5):
    await execute(
        "INSERT INTO agent_facts (session_id, fact, category, importance) VALUES (%s, %s, %s, %s)",
        (session_id, fact[:500], category, min(max(importance, 0), 1)),
    )


async def get_facts(session_id: str = None, limit: int = 20) -> list:
    if session_id:
        rows = await query(
            """
            SELECT id, fact, category, importance, created_at
            FROM agent_facts
            WHERE session_id = %s
              AND created_at > now() - INTERVAL '1 year'
            ORDER BY importance DESC, created_at DESC LIMIT %s
            """,
            (session_id, limit),
        )
    else:
        rows = await query(
            """
            SELECT id, fact, category, importance, created_at
            FROM agent_facts
            WHERE created_at > now() - INTERVAL '1 year'
            ORDER BY importance DESC, created_at DESC LIMIT %s
            """,
            (limit,),
        )
    return [
        {"id": str(r[0]), "fact": r[1], "category": r[2], "importance": r[3], "created_at": str(r[4])}
        for r in rows
    ]


async def run_ttl_cleanup() -> int:
    """Delete expired facts based on category-specific TTL. Returns count deleted."""
    total_deleted = 0
    for category, days in TTL_DAYS.items():
        cnt_rows = await query(
            "SELECT COUNT(*) FROM agent_facts WHERE category = %s AND created_at < now() - MAKE_INTERVAL(days => %s)",
            (category, days),
        )
        total_deleted += cnt_rows[0][0] if cnt_rows else 0
        await execute(
            "DELETE FROM agent_facts WHERE category = %s AND created_at < now() - MAKE_INTERVAL(days => %s)",
            (category, days),
        )
    # Also delete very old (1+ year) facts regardless of category
    cnt_rows = await query(
        "SELECT COUNT(*) FROM agent_facts WHERE created_at < now() - INTERVAL '365 days'"
    )
    total_deleted += cnt_rows[0][0] if cnt_rows else 0
    await execute(
        "DELETE FROM agent_facts WHERE created_at < now() - INTERVAL '365 days'"
    )
    return total_deleted


async def boost_importance(fact_id: str):
    """Boost importance when a fact is accessed/reused."""
    await execute(
        "UPDATE agent_facts SET importance = LEAST(importance + 0.1, 1.0), last_accessed = now() WHERE id = %s",
        (fact_id,),
    )


async def decay_importance():
    """Slowly decay importance of unused facts over time."""
    await execute(
        "UPDATE agent_facts SET importance = GREATEST(importance - 0.01, 0.1) WHERE last_accessed < now() - INTERVAL '7 days'"
    )


async def get_stats() -> dict:
    """Return memory statistics."""
    total_rows = await query("SELECT COUNT(*) FROM agent_facts")
    total = total_rows[0][0] if total_rows else 0
    cat_rows = await query(
        "SELECT category, COUNT(*) as cnt, AVG(importance) as avg_imp FROM agent_facts GROUP BY category"
    )
    by_category = [{"category": r[0], "count": r[1], "avg_importance": float(r[2])} for r in cat_rows]
    return {"total_facts": total, "by_category": by_category, "ttl_policy": TTL_DAYS}


async def clear_facts(session_id: str):
    await execute("DELETE FROM agent_facts WHERE session_id = %s", (session_id,))


async def run_session_cleanup(ttl_days: int = 30) -> int:
    """Delete session messages older than ttl_days and orphaned sessions.

    Returns total rows deleted.
    """
    total = 0
    cnt = await query(
        "SELECT COUNT(*) FROM chat_messages "
        "WHERE created_at < now() - MAKE_INTERVAL(days => %s)",
        (ttl_days,),
    )
    total += cnt[0][0] if cnt else 0
    await execute(
        "DELETE FROM chat_messages WHERE created_at < now() - MAKE_INTERVAL(days => %s)",
        (ttl_days,),
    )
    cnt2 = await query(
        "SELECT COUNT(*) FROM chat_sessions s WHERE NOT EXISTS "
        "(SELECT 1 FROM chat_messages m WHERE m.session_id = s.id) "
        "AND s.created_at < now() - MAKE_INTERVAL(days => %s)",
        (ttl_days,),
    )
    total += cnt2[0][0] if cnt2 else 0
    await execute(
        "DELETE FROM chat_sessions s WHERE NOT EXISTS "
        "(SELECT 1 FROM chat_messages m WHERE m.session_id = s.id) "
        "AND s.created_at < now() - MAKE_INTERVAL(days => %s)",
        (ttl_days,),
    )
    return total

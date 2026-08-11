"""Session persistence backed by PostgreSQL (chat_sessions / chat_messages).

Previously in-memory dict; now survives restarts. All functions are async
and best-effort: callers may wrap them in try/except for graceful degradation.
"""
import uuid
from datetime import datetime
from app.db import query, execute


async def get_or_create_session(session_id: str | None = None) -> dict:
    """Ensure a session row exists; return its summary dict."""
    sid = session_id or str(uuid.uuid4())
    try:
        await execute(
            "INSERT INTO chat_sessions (id) VALUES (%s) ON CONFLICT (id) DO NOTHING",
            (sid,),
        )
        rows = await query(
            "SELECT id, created_at FROM chat_sessions WHERE id = %s", (sid,)
        )
        if rows:
            return {"id": str(rows[0][0]), "messages": [], "created_at": str(rows[0][1])}
    except Exception:
        pass
    # Fallback: virtual session without persistence (DB down)
    return {"id": sid, "messages": [], "created_at": datetime.now().isoformat()}


async def add_message(session_id: str, role: str, content: str) -> None:
    """Append a message to a session (content truncated to 2000 chars)."""
    await get_or_create_session(session_id)
    await execute(
        "INSERT INTO chat_messages (session_id, role, content) VALUES (%s, %s, %s)",
        (session_id, role, content[:2000]),
    )


async def get_history(session_id: str, last_n: int = 10) -> list[dict]:
    """Return the last `last_n` messages in chronological order."""
    rows = await query(
        "SELECT role, content FROM chat_messages "
        "WHERE session_id = %s ORDER BY created_at DESC, id DESC LIMIT %s",
        (session_id, last_n),
    )
    messages = [{"role": r[0], "content": r[1]} for r in rows]
    messages.reverse()
    return messages


async def get_summary(session_id: str) -> dict:
    """Return session metadata + message count."""
    created_at = datetime.now().isoformat()
    try:
        rows = await query(
            "SELECT COUNT(*) FROM chat_messages WHERE session_id = %s", (session_id,)
        )
        count = rows[0][0] if rows else 0
        srow = await query(
            "SELECT created_at FROM chat_sessions WHERE id = %s", (session_id,)
        )
        if srow:
            created_at = str(srow[0][0])
    except Exception:
        count = 0
    return {"session_id": session_id, "message_count": count, "created_at": created_at}


async def clear_session(session_id: str) -> bool:
    """Remove all messages for a session (session row is kept)."""
    await execute("DELETE FROM chat_messages WHERE session_id = %s", (session_id,))
    return True

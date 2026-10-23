"""Session + message persistence (short-term memory, survives refresh)."""
import uuid

import structlog

from app.db import execute, query

logger = structlog.get_logger()

DEFAULT_TITLE = "新对话"
TITLE_MAX = 30
HISTORY_LIMIT = 12          # messages injected into the prompt
ARCHIVE_THRESHOLD = 30      # summarize once a session grows beyond this


async def create_session(user_id: int, title: str = DEFAULT_TITLE) -> dict:
    session_id = str(uuid.uuid4())
    await execute(
        "INSERT INTO sessions (id, user_id, title) VALUES (%s, %s, %s)",
        (session_id, user_id, title),
    )
    return {"id": session_id, "user_id": user_id, "title": title}


async def get_session(session_id: str, user_id: int) -> dict | None:
    rows = await query(
        "SELECT id, title, summary, created_at, updated_at FROM sessions "
        "WHERE id = %s AND user_id = %s",
        (session_id, user_id),
    )
    if not rows:
        return None
    r = rows[0]
    return {"id": str(r[0]), "title": r[1], "summary": r[2], "created_at": r[3], "updated_at": r[4]}


async def list_sessions(user_id: int, limit: int = 50) -> list[dict]:
    rows = await query(
        """
        SELECT s.id, s.title, s.created_at, s.updated_at,
               (SELECT COUNT(*) FROM messages m WHERE m.session_id = s.id)
        FROM sessions s
        WHERE s.user_id = %s
        ORDER BY s.updated_at DESC
        LIMIT %s
        """,
        (user_id, limit),
    )
    return [
        {
            "id": str(r[0]), "title": r[1], "created_at": r[2],
            "updated_at": r[3], "message_count": int(r[4]),
        }
        for r in rows
    ]


async def delete_session(session_id: str, user_id: int) -> bool:
    rows = await execute(
        "DELETE FROM sessions WHERE id = %s AND user_id = %s RETURNING id",
        (session_id, user_id),
    )
    return bool(rows)


async def get_messages(session_id: str, limit: int = 200) -> list[dict]:
    rows = await query(
        "SELECT id, role, content, tool_json, created_at FROM messages "
        "WHERE session_id = %s ORDER BY id ASC LIMIT %s",
        (session_id, limit),
    )
    return [
        {"id": r[0], "role": r[1], "content": r[2], "tool_json": r[3], "created_at": r[4]}
        for r in rows
    ]


async def recent_messages(session_id: str, limit: int = HISTORY_LIMIT) -> list[dict]:
    rows = await query(
        "SELECT role, content FROM messages WHERE session_id = %s "
        "AND role IN ('user','assistant') ORDER BY id DESC LIMIT %s",
        (session_id, limit),
    )
    return [{"role": r[0], "content": r[1]} for r in reversed(rows)]


async def add_message(
    session_id: str,
    role: str,
    content: str,
    tool_json: dict | None = None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
) -> int:
    import json
    rows = await execute(
        """
        INSERT INTO messages (session_id, role, content, tool_json, prompt_tokens, completion_tokens)
        VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
        """,
        (
            session_id, role, content,
            json.dumps(tool_json, ensure_ascii=False) if tool_json else None,
            prompt_tokens, completion_tokens,
        ),
    )
    await execute("UPDATE sessions SET updated_at = now() WHERE id = %s", (session_id,))
    return rows[0][0] if rows else 0


async def maybe_set_title(session_id: str, first_user_content: str) -> str:
    """Set a readable title from the first user message if still default."""
    title = first_user_content.strip().replace("\n", " ")[:TITLE_MAX] or DEFAULT_TITLE
    await execute(
        "UPDATE sessions SET title = %s WHERE id = %s AND (title = %s OR title IS NULL)",
        (title, session_id, DEFAULT_TITLE),
    )
    return title


async def count_messages(session_id: str) -> int:
    rows = await query("SELECT COUNT(*) FROM messages WHERE session_id = %s", (session_id,))
    return int(rows[0][0]) if rows else 0


async def set_summary(session_id: str, summary: str) -> None:
    await execute("UPDATE sessions SET summary = %s WHERE id = %s", (summary, session_id))
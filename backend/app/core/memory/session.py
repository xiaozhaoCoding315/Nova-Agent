"""Session + message persistence (short-term memory, survives refresh)."""
import json
import uuid

import structlog

from app.db import execute, query, transaction

logger = structlog.get_logger()

DEFAULT_TITLE = "新对话"
TITLE_MAX = 30
HISTORY_LIMIT = 12          # messages injected into the prompt
ARCHIVE_THRESHOLD = 30      # summarize once a session grows beyond this


async def create_session(
    user_id: int,
    title: str = DEFAULT_TITLE,
    model: str | None = None,
    repo_ids: list[str] | None = None,
) -> dict:
    session_id = str(uuid.uuid4())
    await execute(
        "INSERT INTO sessions (id, user_id, title, model) VALUES (%s, %s, %s, %s)",
        (session_id, user_id, title, model),
    )
    if repo_ids:
        await set_repo_ids(session_id, repo_ids, user_id=user_id)
    return {
        "id": session_id, "user_id": user_id, "title": title,
        "permission_mode": "ask", "repo_ids": list(repo_ids or []), "model": model,
        "primary_repo_id": (repo_ids or [None])[0],
    }


async def get_session(session_id: str, user_id: int) -> dict | None:
    rows = await query(
        """
        SELECT s.id, s.title, s.summary, s.permission_mode, s.created_at, s.updated_at,
               COALESCE((
                   SELECT jsonb_agg(sr.repo_id ORDER BY sr.created_at)
                   FROM session_repos sr WHERE sr.session_id = s.id
               ), '[]'::jsonb),
               s.summary_upto_id, s.model, s.primary_repo_id
        FROM sessions s
        WHERE s.id = %s AND s.user_id = %s
        """,
        (session_id, user_id),
    )
    if not rows:
        return None
    r = rows[0]
    return {
        "id": str(r[0]), "title": r[1], "summary": r[2],
        "permission_mode": r[3] or "ask", "created_at": r[4], "updated_at": r[5],
        "repo_ids": [str(x) for x in (r[6] or [])],
        "summary_upto_id": int(r[7] or 0),
        "model": r[8],
        "primary_repo_id": str(r[9]) if r[9] else None,
    }


async def list_sessions(
    user_id: int, limit: int = 50, repo_id: str | None = None
) -> list[dict]:
    repo_clause = ""
    params: list = [user_id]
    if repo_id:
        repo_clause = (
            "AND EXISTS (SELECT 1 FROM session_repos sr "
            "WHERE sr.session_id = s.id AND sr.repo_id::text = %s)"
        )
        params.append(repo_id)
    params.append(limit)
    rows = await query(
        f"""
        SELECT s.id, s.title, s.created_at, s.updated_at,
               (SELECT COUNT(*) FROM messages m WHERE m.session_id = s.id),
               s.permission_mode,
               COALESCE((
                   SELECT jsonb_agg(sr.repo_id ORDER BY sr.created_at)
                   FROM session_repos sr WHERE sr.session_id = s.id
               ), '[]'::jsonb),
               s.model, s.primary_repo_id
        FROM sessions s
        WHERE s.user_id = %s {repo_clause}
        ORDER BY s.updated_at DESC
        LIMIT %s
        """,
        tuple(params),
    )
    return [
        {
            "id": str(r[0]), "title": r[1], "created_at": r[2],
            "updated_at": r[3], "message_count": int(r[4]),
            "permission_mode": r[5] or "ask",
            "repo_ids": [str(x) for x in (r[6] or [])],
            "model": r[7],
            "primary_repo_id": str(r[8]) if r[8] else None,
        }
        for r in rows
    ]


async def delete_session(session_id: str, user_id: int) -> bool:
    rows = await execute(
        "DELETE FROM sessions WHERE id = %s AND user_id = %s RETURNING id",
        (session_id, user_id),
    )
    return bool(rows)


async def rename_session(session_id: str, user_id: int, title: str) -> dict | None:
    rows = await execute(
        "UPDATE sessions SET title = %s, updated_at = now() "
        "WHERE id = %s AND user_id = %s RETURNING id, title, created_at, updated_at",
        (title[:200], session_id, user_id),
    )
    if not rows:
        return None
    r = rows[0]
    return {"id": str(r[0]), "title": r[1], "created_at": r[2], "updated_at": r[3]}


async def get_messages(
    session_id: str, limit: int = 200, user_id: int | None = None
) -> list[dict]:
    owner = ""
    owner_params: list = []
    if user_id is not None:
        owner = (
            "AND EXISTS (SELECT 1 FROM sessions s "
            "WHERE s.id = messages.session_id AND s.user_id = %s)"
        )
        owner_params.append(user_id)
    rows = await query(
        "SELECT id, role, content, tool_json, attachments, created_at FROM messages "
        f"WHERE session_id = %s {owner} ORDER BY id ASC LIMIT %s",
        (session_id, *owner_params, limit),
    )
    return [
        {
            "id": r[0], "role": r[1], "content": r[2], "tool_json": r[3],
            "attachments": r[4] or [], "created_at": r[5],
        }
        for r in rows
    ]


async def recent_messages(
    session_id: str, limit: int = HISTORY_LIMIT, after_id: int = 0,
    user_id: int | None = None,
) -> list[dict]:
    sql = (
        "SELECT role, content FROM messages WHERE session_id = %s "
        "AND role IN ('user','assistant')"
    )
    params: list = [session_id]
    if user_id is not None:
        sql += (
            " AND EXISTS (SELECT 1 FROM sessions s "
            "WHERE s.id = messages.session_id AND s.user_id = %s)"
        )
        params.append(user_id)
    if after_id > 0:
        sql += " AND id > %s"
        params.append(after_id)
    sql += " ORDER BY id DESC LIMIT %s"
    params.append(limit)
    rows = await query(sql, tuple(params))
    return [{"role": r[0], "content": r[1]} for r in reversed(rows)]


async def messages_after(
    session_id: str, after_id: int = 0, user_id: int | None = None
) -> list[dict]:
    owner = ""
    owner_params: list = []
    if user_id is not None:
        owner = (
            "AND EXISTS (SELECT 1 FROM sessions s "
            "WHERE s.id = messages.session_id AND s.user_id = %s)"
        )
        owner_params.append(user_id)
    rows = await query(
        "SELECT id, role, content FROM messages WHERE session_id = %s AND id > %s "
        f"AND role IN ('user','assistant') {owner} ORDER BY id ASC",
        (session_id, after_id, *owner_params),
    )
    return [{"id": int(r[0]), "role": r[1], "content": r[2]} for r in rows]


async def summary_state(session_id: str, user_id: int) -> tuple[str, int] | None:
    rows = await query(
        "SELECT summary, summary_upto_id FROM sessions WHERE id = %s AND user_id = %s",
        (session_id, user_id),
    )
    if not rows:
        return None
    return (rows[0][0] or "", int(rows[0][1] or 0))


async def add_message(
    session_id: str,
    role: str,
    content: str,
    tool_json: dict | None = None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    attachments: list[dict] | None = None,
) -> int:
    import json
    rows = await execute(
        """
        INSERT INTO messages
        (session_id, role, content, tool_json, attachments, prompt_tokens, completion_tokens)
        VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id
        """,
        (
            session_id, role, content,
            json.dumps(tool_json, ensure_ascii=False) if tool_json else None,
            json.dumps(attachments or [], ensure_ascii=False, default=str),
            prompt_tokens, completion_tokens,
        ),
    )
    await execute("UPDATE sessions SET updated_at = now() WHERE id = %s", (session_id,))
    return rows[0][0] if rows else 0


async def set_repo_ids(
    session_id: str, repo_ids: list[str], user_id: int | None = None
) -> None:
    repo_ids = list(dict.fromkeys(repo_ids))
    if user_id is not None:
        owned = await query(
            "SELECT 1 FROM sessions WHERE id = %s AND user_id = %s",
            (session_id, user_id),
        )
        if not owned:
            raise ValueError("会话不存在或无权访问")
        if repo_ids:
            rows = await query(
                "SELECT id FROM repos WHERE id = ANY(%s::uuid[]) AND user_id = %s",
                (repo_ids, user_id),
            )
            if len(rows) != len(repo_ids):
                raise ValueError("仓库不存在或无权访问")

    statements: list[tuple] = [
        ("DELETE FROM session_repos WHERE session_id = %s", (session_id,)),
    ]
    for repo_id in repo_ids:
        statements.append((
            "INSERT INTO session_repos (session_id, repo_id) VALUES (%s, %s) "
            "ON CONFLICT DO NOTHING",
            (session_id, repo_id),
        ))
    statements.append((
        "UPDATE sessions SET primary_repo_id = %s, repo_ids = %s, updated_at = now() "
        "WHERE id = %s",
        (
            repo_ids[0] if repo_ids else None,
            json.dumps(repo_ids, ensure_ascii=False),
            session_id,
        ),
    ))
    await transaction(statements)


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


async def count_messages_since(
    session_id: str, after_id: int = 0, user_id: int | None = None
) -> int:
    owner = ""
    owner_params: list = []
    if user_id is not None:
        owner = (
            "AND EXISTS (SELECT 1 FROM sessions s "
            "WHERE s.id = messages.session_id AND s.user_id = %s)"
        )
        owner_params.append(user_id)
    rows = await query(
        "SELECT COUNT(*) FROM messages WHERE session_id = %s AND id > %s "
        f"AND role IN ('user','assistant') {owner}",
        (session_id, after_id, *owner_params),
    )
    return int(rows[0][0]) if rows else 0


async def set_summary(session_id: str, summary: str, upto_id: int) -> None:
    await execute(
        "UPDATE sessions SET summary = %s, summary_upto_id = %s WHERE id = %s",
        (summary, upto_id, session_id),
    )
"""Storage for the middle of tool results that in-turn compaction dropped.

Compaction is the point where context is lost; Anthropic's own guidance is
that it must stay recoverable.  Each shrunk tool result spills its dropped
middle here and leaves a token in the placeholder, so the model can read the
original back with ``context_read`` when a later step actually needs it.

Rows are scoped to a session and expire with it.  Content is redacted before
storage: the blob is read by the model later, and the loop's privacy boundary
must not be bypassed by going around it.
"""
from __future__ import annotations

import uuid

import structlog

from app.core.security.redaction import redact_text
from app.db import execute, query

logger = structlog.get_logger()

MAX_BLOB_CHARS = 60_000


async def save_blobs(
    session_id: str,
    items: list[tuple[str, str]],
    *,
    turn_id: str | None = None,
) -> list[int]:
    """Persist spilled originals in one round trip; returns their ids."""
    if not items:
        return []
    ids: list[int] = []
    try:
        for tool_name, text in items:
            rows = await execute(
                "INSERT INTO context_blobs (session_id, turn_id, tool_name, content) "
                "VALUES (%s, %s, %s, %s) RETURNING id",
                (
                    session_id,
                    turn_id if _is_uuid(turn_id) else None,
                    (tool_name or "")[:64],
                    redact_text(text)[:MAX_BLOB_CHARS],
                ),
            )
            if rows:
                ids.append(int(rows[0][0]))
    except Exception as exc:  # noqa: BLE001 — never break a turn for bookkeeping
        logger.warning("context_blob_save_failed", session=session_id, error=str(exc))
    return ids


async def read_blob(blob_id: int, session_id: str, user_id: int) -> dict | None:
    """Read one blob, but only if it belongs to this user's session."""
    try:
        rows = await query(
            "SELECT b.id, b.tool_name, b.content, b.created_at "
            "FROM context_blobs b JOIN sessions s ON s.id = b.session_id "
            "WHERE b.id = %s AND b.session_id = %s AND s.user_id = %s",
            (blob_id, session_id, user_id),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("context_blob_read_failed", blob=blob_id, error=str(exc))
        return None
    if not rows:
        return None
    row = rows[0]
    return {
        "id": int(row[0]),
        "tool": str(row[1] or ""),
        "content": str(row[2] or ""),
        "truncated": len(str(row[2] or "")) >= MAX_BLOB_CHARS,
    }


async def purge_session_blobs(session_id: str) -> int:
    """Drop a session's blobs (session deletion cascades, this is for tests)."""
    try:
        rows = await execute(
            "DELETE FROM context_blobs WHERE session_id = %s RETURNING id",
            (session_id,),
        )
        return len(rows or [])
    except Exception:  # noqa: BLE001
        return 0


def _is_uuid(value: str | None) -> bool:
    if not value:
        return False
    try:
        uuid.UUID(str(value))
        return True
    except (ValueError, AttributeError, TypeError):
        return False

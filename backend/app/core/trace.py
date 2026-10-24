"""Append-only trajectory events (replay, debugging, CI audit).

Every record is best-effort: tracing must never break the agent loop.
"""
import json

import structlog

from app.core.security.redaction import redact_obj
from app.db import execute

logger = structlog.get_logger()


async def record(session_id: str, turn_id: str, kind: str, payload: dict | None = None) -> None:
    try:
        safe_payload = redact_obj(payload or {})
        await execute(
            "INSERT INTO trace_events (session_id, turn_id, kind, payload) "
            "VALUES (%s, %s, %s, %s)",
            (session_id, turn_id, kind, json.dumps(safe_payload, ensure_ascii=False, default=str)),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("trace_record_failed", kind=kind, error=str(exc))


async def list_events(
    session_id: str, limit: int = 500, user_id: int | None = None
) -> list[dict]:
    from app.db import query
    owner = ""
    params: list = []
    if user_id is not None:
        owner = (
            "AND EXISTS (SELECT 1 FROM sessions s "
            "WHERE s.id = trace_events.session_id AND s.user_id = %s)"
        )
        params.append(user_id)
    params.extend([session_id, limit])
    rows = await query(
        "SELECT id, turn_id, kind, payload, created_at FROM trace_events "
        f"WHERE session_id = %s {owner} ORDER BY id ASC LIMIT %s",
        tuple(params),
    )
    return [
        {
            "id": r[0], "turn_id": str(r[1]) if r[1] else None, "kind": r[2],
            "payload": r[3] or {}, "created_at": r[4],
        }
        for r in rows
    ]
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


async def list_events(session_id: str, limit: int = 500) -> list[dict]:
    from app.db import query
    rows = await query(
        "SELECT id, turn_id, kind, payload, created_at FROM trace_events "
        "WHERE session_id = %s ORDER BY id ASC LIMIT %s",
        (session_id, limit),
    )
    return [
        {
            "id": r[0], "turn_id": str(r[1]) if r[1] else None, "kind": r[2],
            "payload": r[3] or {}, "created_at": r[4],
        }
        for r in rows
    ]
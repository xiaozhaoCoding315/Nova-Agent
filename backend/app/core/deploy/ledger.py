"""Idempotency ledger for external actions (deploy, teardown, future APIs)."""
import json
import uuid

from app.db import execute, query


def _row_to_dict(row) -> dict:
    return {
        "id": str(row[0]), "user_id": row[1], "idempotency_key": row[2],
        "action": row[3], "target": row[4], "status": row[5],
        "request": row[6] or {}, "response": row[7] or {}, "error": row[8],
        "created_at": row[9], "updated_at": row[10], "finished_at": row[11],
    }


async def get(key: str) -> dict | None:
    rows = await query(
        "SELECT id, user_id, idempotency_key, action, target, status, request, "
        "response, error, created_at, updated_at, finished_at "
        "FROM external_actions WHERE idempotency_key = %s",
        (key,),
    )
    return _row_to_dict(rows[0]) if rows else None


async def begin(
    user_id: int, key: str, action: str, target: str, request: dict
) -> dict:
    existing = await get(key)
    if existing:
        return existing
    action_id = str(uuid.uuid4())
    try:
        await execute(
            "INSERT INTO external_actions "
            "(id, user_id, idempotency_key, action, target, status, request) "
            "VALUES (%s, %s, %s, %s, %s, 'pending', %s)",
            (action_id, user_id, key, action, target[:240],
             json.dumps(request, ensure_ascii=False)),
        )
    except Exception:
        # A concurrent request won the unique key race.
        existing = await get(key)
        if existing:
            return existing
        raise
    return await get(key) or {
        "id": action_id, "user_id": user_id, "idempotency_key": key,
        "action": action, "target": target, "status": "pending",
        "request": request, "response": {}, "error": None,
    }


async def mark_pending(key: str) -> None:
    await execute(
        "UPDATE external_actions SET status = 'pending', error = NULL, "
        "finished_at = NULL, updated_at = now() WHERE idempotency_key = %s",
        (key,),
    )


async def finish(
    key: str, status: str, response: dict | None = None, error: str | None = None
) -> None:
    await execute(
        "UPDATE external_actions SET status = %s, response = %s, error = %s, "
        "finished_at = now(), updated_at = now() WHERE idempotency_key = %s",
        (status, json.dumps(response or {}, ensure_ascii=False),
         error[:2000] if error else None, key),
    )

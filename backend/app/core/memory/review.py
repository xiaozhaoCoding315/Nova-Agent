"""Human review queue for risky memory writes and merges.

Facts written by automatic extraction may be high-risk (credentials,
deployment, permissions, prompt injection) or conflict with an explicit topic.
Nightly consolidation also routes risky merges here instead of silently
archiving a fact.  The queue is the only path that activates such facts.
"""
from __future__ import annotations

import json

import structlog

from app.db import execute, query

logger = structlog.get_logger()

KIND_HIGH_RISK = "high_risk_fact"
KIND_MERGE = "merge"
KIND_CONFLICT = "conflict"
KINDS = (KIND_HIGH_RISK, KIND_MERGE, KIND_CONFLICT)

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUSES = (STATUS_PENDING, STATUS_APPROVED, STATUS_REJECTED)
MAX_ITEMS = 100

_COLUMNS = (
    "id, kind, fact_id, target_fact_id, status, reason, payload, created_at"
)
# Qualified copy: list_items joins ``facts`` twice, so bare ``id`` is ambiguous.
_Q_COLUMNS = (
    "q.id, q.kind, q.fact_id, q.target_fact_id, q.status, q.reason, "
    "q.payload, q.created_at"
)


def _payload(value) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError):
            return {}
    return {}


def _from_row(row) -> dict:
    return {
        "id": int(row[0]),
        "kind": row[1],
        "fact_id": row[2],
        "target_fact_id": row[3],
        "status": row[4] or STATUS_PENDING,
        "reason": row[5] or "",
        "payload": _payload(row[6]),
        "created_at": row[7] if len(row) > 7 else None,
    }


async def enqueue(
    user_id: int,
    kind: str,
    fact_id: int,
    target_fact_id: int | None = None,
    reason: str = "",
    payload: dict | None = None,
) -> None:
    if kind not in KINDS:
        raise ValueError("未知的复核类型")
    try:
        await execute(
            "INSERT INTO memory_review_queue "
            "(user_id, kind, fact_id, target_fact_id, reason, payload) "
            "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
            (
                user_id, kind, fact_id, target_fact_id, (reason or "")[:300],
                json.dumps(payload or {}, ensure_ascii=False),
            ),
        )
    except Exception as exc:  # noqa: BLE001 — review is best-effort on write
        logger.warning("memory_review_enqueue_failed", error=str(exc))


async def list_items(
    user_id: int, status: str = STATUS_PENDING, limit: int = 50,
) -> list[dict]:
    if status not in STATUSES:
        raise ValueError("复核状态只能是 pending、approved 或 rejected")
    rows = await query(
        f"SELECT {_Q_COLUMNS}, "
        "f.content, f.one_line, f.category, f.scope_type, f.scope_id, "
        "t.content "
        "FROM memory_review_queue q "
        "LEFT JOIN facts f ON f.id = q.fact_id "
        "LEFT JOIN facts t ON t.id = q.target_fact_id "
        "WHERE q.user_id = %s AND q.status = %s "
        "ORDER BY q.created_at DESC LIMIT %s",
        (user_id, status, max(1, min(int(limit), MAX_ITEMS))),
    )
    items: list[dict] = []
    for row in rows:
        item = _from_row(row[:8])
        item.update({
            "content": row[8] or "",
            "one_line": row[9] or "",
            "category": row[10] or "fact",
            "scope_type": row[11] or "global",
            "scope_id": row[12] or "",
            "target_content": row[13] if len(row) > 13 else None,
        })
        items.append(item)
    return items


async def get_item(user_id: int, queue_id: int) -> dict | None:
    rows = await query(
        f"SELECT {_COLUMNS} FROM memory_review_queue "
        "WHERE id = %s AND user_id = %s",
        (queue_id, user_id),
    )
    return _from_row(rows[0]) if rows else None


async def resolve(user_id: int, queue_id: int, approve: bool) -> dict | None:
    """Apply the decision.  Returns ``None`` when already handled/missing."""
    item = await get_item(user_id, queue_id)
    if item is None or item["status"] != STATUS_PENDING:
        return None
    kind = item["kind"]
    fact_id = item["fact_id"]
    target_id = item["target_fact_id"]

    if approve:
        if kind == KIND_HIGH_RISK:
            await execute(
                "UPDATE facts SET status = 'active', updated_at = now() "
                "WHERE id = %s AND user_id = %s",
                (fact_id, user_id),
            )
        elif kind == KIND_MERGE:
            await execute(
                "UPDATE facts SET status = 'archived', merged_into_id = %s, "
                "updated_at = now() WHERE id = %s AND user_id = %s",
                (target_id, fact_id, user_id),
            )
        elif kind == KIND_CONFLICT and target_id:
            await execute(
                "UPDATE facts SET status = 'superseded', updated_at = now() "
                "WHERE id = %s AND user_id = %s",
                (target_id, user_id),
            )
            await execute(
                "UPDATE facts SET status = 'active', version = version + 1, "
                "supersedes_id = %s, updated_at = now() "
                "WHERE id = %s AND user_id = %s",
                (target_id, fact_id, user_id),
            )
    else:
        if kind == KIND_HIGH_RISK:
            await execute(
                "UPDATE facts SET status = 'archived', updated_at = now() "
                "WHERE id = %s AND user_id = %s",
                (fact_id, user_id),
            )
        elif kind == KIND_CONFLICT:
            await execute(
                "UPDATE facts SET status = 'archived', updated_at = now() "
                "WHERE id = %s AND user_id = %s",
                (fact_id, user_id),
            )

    status = STATUS_APPROVED if approve else STATUS_REJECTED
    await execute(
        "UPDATE memory_review_queue SET status = %s, resolved_at = now() "
        "WHERE id = %s AND user_id = %s",
        (status, queue_id, user_id),
    )
    await log_resolution(user_id, item, status)
    item["status"] = status
    return item


async def log_resolution(user_id: int, item: dict, status: str) -> None:
    """Audit trail is best-effort; the queue row remains the source of truth."""
    try:
        from app.core.security.audit import log_audit

        await log_audit(
            "memory_review_resolve", user_id=str(user_id),
            details={
                "id": item["id"], "kind": item["kind"],
                "fact_id": item["fact_id"],
                "target_fact_id": item["target_fact_id"],
                "status": status,
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("memory_review_audit_failed", error=str(exc))

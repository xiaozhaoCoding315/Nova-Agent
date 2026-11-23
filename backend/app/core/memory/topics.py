"""Deterministic topic index over active facts.

This is intentionally computed from facts instead of an LLM-written wiki:
topic counts and representative one-liners must stay reproducible and free of
hallucinated summaries.  Nightly maintenance reports the topic count; the API
exposes the current index to the settings UI.
"""
from __future__ import annotations

from app.core.memory import scope as scope_mod
from app.core.security.redaction import redact_text
from app.db import query

MAX_TOPICS = 50
MAX_SAMPLES = 3


def _scope_filter(scopes: list[scope_mod.Scope] | None) -> tuple[str, list]:
    if scopes is None:
        return "", []
    if not scopes:
        return " AND FALSE", []
    parts: list[str] = []
    params: list = []
    for scope in scopes:
        parts.append("(scope_type = %s AND scope_id = %s)")
        params.extend([scope.type, scope.id])
    return " AND (" + " OR ".join(parts) + ")", params


async def build_topic_index(
    user_id: int,
    scopes: list[scope_mod.Scope] | None = None,
    limit: int = 20,
) -> list[dict]:
    scope_sql, scope_params = _scope_filter(scopes)
    rows = await query(
        "SELECT COALESCE(NULLIF(topic, ''), category) AS topic_label, "
        "scope_type, scope_id, COUNT(*) AS total, MAX(updated_at), "
        "(ARRAY_AGG(one_line ORDER BY importance DESC, last_used_at DESC))[1:3] "
        "FROM facts WHERE user_id = %s AND status = 'active' "
        f"{scope_sql} "
        "GROUP BY COALESCE(NULLIF(topic, ''), category), scope_type, scope_id "
        "ORDER BY total DESC, MAX(updated_at) DESC LIMIT %s",
        (
            user_id, *scope_params,
            max(1, min(int(limit), MAX_TOPICS)),
        ),
    )
    result: list[dict] = []
    for row in rows:
        samples = row[5] if isinstance(row[5], list) else []
        result.append({
            "topic": row[0] or "未分类",
            "scope_type": row[1] or scope_mod.GLOBAL,
            "scope_id": row[2] or "",
            "count": int(row[3] or 0),
            "updated_at": row[4],
            "samples": [
                redact_text(str(item))[:160] for item in samples[:MAX_SAMPLES]
            ],
        })
    return result


async def count_topics() -> int:
    rows = await query(
        "SELECT COUNT(*) FROM ("
        "  SELECT DISTINCT user_id, COALESCE(NULLIF(topic, ''), category) "
        "  FROM facts WHERE status = 'active'"
        ") AS topics"
    )
    return int(rows[0][0]) if rows else 0


def format_topic_block(rows: list[dict]) -> str:
    if not rows:
        return ""
    lines = [
        f"- {row['topic']}（{row['count']} 条）："
        + "；".join(row.get("samples") or [])
        for row in rows[:MAX_TOPICS]
    ]
    return "\n\n## 记忆主题索引（确定性统计，只作背景）\n" + "\n".join(lines)

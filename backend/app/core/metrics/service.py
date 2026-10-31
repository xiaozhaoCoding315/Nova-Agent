"""Delivery metrics aggregated from tasks, usage and jobs."""
from datetime import datetime, timezone

from app.db import query


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 3) if denominator else 0.0


async def compute_metrics(user_id: int, days: int = 7) -> dict:
    days = max(1, min(int(days), 90))
    tasks = await query(
        "SELECT COUNT(*), "
        "COUNT(*) FILTER (WHERE status IN ('ready', 'applied')), "
        "COUNT(*) FILTER (WHERE COALESCE((result->>'repair_attempts')::int, 0) > 0), "
        "COUNT(*) FILTER (WHERE status IN ('ready', 'applied') "
        "  AND COALESCE((result->>'repair_attempts')::int, 0) = 0) "
        "FROM tasks WHERE user_id = %s "
        "AND created_at >= now() - make_interval(days => %s)",
        (user_id, days),
    )
    tasks_total, tasks_verified, tasks_repaired, tasks_first_pass = tasks[0]

    approval = await query(
        "SELECT AVG(EXTRACT(EPOCH FROM (applied_at - created_at)) / 60.0) "
        "FROM edits WHERE user_id = %s AND applied_at IS NOT NULL "
        "AND created_at >= now() - make_interval(days => %s)",
        (user_id, days),
    )
    approval_minutes = approval[0][0] if approval and approval[0][0] is not None else None

    tokens = await query(
        "SELECT COALESCE(SUM(prompt_tokens + completion_tokens), 0) FROM usage_log "
        "WHERE user_id = %s AND created_at >= now() - make_interval(days => %s)",
        (user_id, days),
    )

    jobs = await query(
        "SELECT percentile_cont(0.95) WITHIN GROUP ("
        "  ORDER BY EXTRACT(EPOCH FROM (finished_at - started_at))) "
        "FROM jobs WHERE user_id = %s AND started_at IS NOT NULL AND finished_at IS NOT NULL "
        "AND created_at >= now() - make_interval(days => %s)",
        (user_id, days),
    )

    tools = await query(
        "SELECT e.payload->>'name' AS name, "
        "  COUNT(*) AS calls, "
        "  COUNT(*) FILTER (WHERE COALESCE((e.payload->>'ok')::boolean, false)) AS ok_calls, "
        "  AVG((e.payload->>'ms')::int) AS avg_ms, "
        "  percentile_cont(0.95) WITHIN GROUP (ORDER BY (e.payload->>'ms')::int) AS p95_ms, "
        "  COUNT(*) FILTER (WHERE e.payload->>'error_class' = 'policy') AS policy_denials, "
        "  COUNT(*) FILTER (WHERE e.payload->>'error_class' IN ('business', 'invalid_args')) "
        "    AS business_errors, "
        "  COUNT(*) FILTER (WHERE e.payload->>'error_class' IN ('infra', 'unknown_tool', 'hook')) "
        "    AS infra_errors "
        "FROM trace_events e JOIN sessions s ON s.id = e.session_id "
        "WHERE s.user_id = %s AND e.kind = 'tool_result' "
        "  AND e.created_at >= now() - make_interval(days => %s) "
        "  AND e.payload ? 'name' "
        "GROUP BY 1 ORDER BY calls DESC LIMIT 20",
        (user_id, days),
    )

    return {
        "window_days": days,
        "tasks_total": int(tasks_total or 0),
        "first_gate_pass_rate": _rate(int(tasks_first_pass or 0), int(tasks_verified or 0)),
        "rework_rate": _rate(int(tasks_repaired or 0), int(tasks_total or 0)),
        "approval_minutes_avg": round(float(approval_minutes), 1) if approval_minutes is not None else None,
        "tokens_total": int(tokens[0][0] or 0) if tokens else 0,
        "p95_job_seconds": round(float(jobs[0][0]), 1) if jobs and jobs[0][0] is not None else None,
        "tool_metrics": [
            {
                "name": row[0] or "unknown",
                "calls": int(row[1] or 0),
                "ok_rate": _rate(int(row[2] or 0), int(row[1] or 0)),
                "avg_ms": round(float(row[3]), 1) if row[3] is not None else None,
                "p95_ms": round(float(row[4]), 1) if row[4] is not None else None,
                "policy_denials": int(row[5] or 0),
                "business_errors": int(row[6] or 0),
                "infra_errors": int(row[7] or 0),
            }
            for row in tools
        ],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

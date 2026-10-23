"""Delivery metrics aggregated from tasks, changes, usage and jobs."""
from datetime import datetime, timezone

from app.db import query


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 3) if denominator else 0.0


async def compute_metrics(user_id: int, days: int = 7) -> dict:
    days = max(1, min(int(days), 90))
    changes = await query(
        "SELECT COUNT(*), "
        "COUNT(*) FILTER (WHERE status = 'applied'), "
        "COUNT(*) FILTER (WHERE status = 'failed') "
        "FROM change_requests WHERE user_id = %s "
        "AND created_at >= now() - make_interval(days => %s)",
        (user_id, days),
    )
    changes_total, accepted_changes, _failed_changes = changes[0]

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

    return {
        "window_days": days,
        "accepted_changes": int(accepted_changes or 0),
        "changes_total": int(changes_total or 0),
        "tasks_total": int(tasks_total or 0),
        "first_gate_pass_rate": _rate(int(tasks_first_pass or 0), int(tasks_verified or 0)),
        "rework_rate": _rate(int(tasks_repaired or 0), int(tasks_total or 0)),
        "approval_minutes_avg": round(float(approval_minutes), 1) if approval_minutes is not None else None,
        "tokens_total": int(tokens[0][0] or 0) if tokens else 0,
        "p95_job_seconds": round(float(jobs[0][0]), 1) if jobs and jobs[0][0] is not None else None,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

"""Night queue: run approved changes / bug tasks unattended inside a night
window, one at a time, under the user's daily token budget.

Approval stays human: the queue only executes the pipelines (SPEC → plan →
Gate → review for changes; red-green for tasks).  Applying the result to the
repository is still a morning decision via the usual approve buttons.
"""
import json
import uuid
from datetime import datetime

import structlog

from app.config import settings
from app.core.security.limits import daily_token_budget, tokens_used_today
from app.db import execute, query

logger = structlog.get_logger()

KINDS = ("change_execute", "task")


async def enqueue_item(
    user_id: int,
    kind: str,
    *,
    change_id: str | None = None,
    repo_id: str | None = None,
    bug_report: str | None = None,
    title: str | None = None,
) -> dict:
    if kind not in KINDS:
        raise ValueError("kind 必须是 change_execute 或 task")
    item_id = str(uuid.uuid4())
    payload: dict = {}
    if kind == "change_execute":
        if not change_id:
            raise ValueError("需要 change_id")
        rows = await query(
            "SELECT title, status FROM change_requests WHERE id = %s AND user_id = %s",
            (change_id, user_id),
        )
        if not rows:
            raise ValueError("变更不存在或无权访问")
        if rows[0][1] not in ("plan_approved", "failed"):
            raise ValueError("只有「计划已批准」的变更才能排入夜间执行")
        payload["change_id"] = str(change_id)
        title = title or rows[0][0]
    else:
        if not repo_id or not (bug_report or "").strip():
            raise ValueError("修复任务需要 repo_id 与 bug 描述")
        rows = await query(
            "SELECT name, status FROM repos WHERE id = %s AND user_id = %s",
            (repo_id, user_id),
        )
        if not rows:
            raise ValueError("仓库不存在或无权访问")
        if rows[0][1] != "ready":
            raise ValueError("仓库尚未完成索引")
        payload["repo_id"] = str(repo_id)
        payload["bug_report"] = bug_report.strip()[:8000]
        title = title or bug_report.strip().splitlines()[0][:120]
    await execute(
        "INSERT INTO night_queue (id, user_id, kind, target_id, payload, title) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (item_id, user_id, kind, change_id,
         json.dumps(payload, ensure_ascii=False), (title or "")[:200]),
    )
    return {"id": item_id, "kind": kind, "title": title, "status": "pending"}


async def list_items(user_id: int, limit: int = 50) -> list[dict]:
    rows = await query(
        "SELECT id, kind, target_id, payload, title, status, job_id, error, "
        "created_at, started_at, finished_at FROM night_queue "
        "WHERE user_id = %s ORDER BY created_at DESC LIMIT %s",
        (user_id, limit),
    )
    return [
        {
            "id": str(r[0]), "kind": r[1], "target_id": str(r[2]) if r[2] else None,
            "payload": r[3] or {}, "title": r[4] or "", "status": r[5],
            "job_id": str(r[6]) if r[6] else None, "error": r[7],
            "created_at": r[8], "started_at": r[9], "finished_at": r[10],
        }
        for r in rows
    ]


async def cancel_item(item_id: str, user_id: int) -> bool:
    rows = await execute(
        "DELETE FROM night_queue WHERE id = %s AND user_id = %s AND status = 'pending' "
        "RETURNING id",
        (item_id, user_id),
    )
    return bool(rows)


def _in_window(now: datetime | None = None) -> bool:
    now = now or datetime.now()
    start, end = settings.night_window_start, settings.night_window_end
    if start <= end:
        return start <= now.hour < end
    return now.hour >= start or now.hour < end  # window crosses midnight


async def _budget_exhausted(user_id: int) -> bool:
    budget = await _user_budget(user_id)
    if budget <= 0:
        return False  # unlimited
    used = await tokens_used_today(user_id)
    return used >= budget * (1.0 - settings.night_budget_reserve)


async def _user_budget(user_id: int) -> int:
    rows = await query(
        "SELECT role, is_guest, quota_daily_tokens, self_daily_tokens FROM users WHERE id = %s",
        (user_id,),
    )
    if not rows:
        return 0
    user = {
        "id": user_id, "role": rows[0][0], "is_guest": bool(rows[0][1]),
        "quota_daily_tokens": rows[0][2], "self_daily_tokens": rows[0][3],
    }
    return daily_token_budget(user)


async def _reconcile_running() -> None:
    """Mark night items done/failed once their underlying job finished."""
    from app.core.jobs.runner import runner

    rows = await query(
        "SELECT id, user_id, job_id FROM night_queue WHERE status = 'running' LIMIT 20"
    )
    for item_id, user_id, job_id in rows:
        if not job_id:
            continue
        job = await runner.get(str(job_id), user_id)
        if not job:
            continue
        status = job.get("status")
        if status == "succeeded":
            await execute(
                "UPDATE night_queue SET status = 'done', finished_at = now(), "
                "error = NULL WHERE id = %s",
                (item_id,),
            )
        elif status in ("failed", "cancelled"):
            await execute(
                "UPDATE night_queue SET status = 'failed', finished_at = now(), "
                "error = %s WHERE id = %s",
                (f"任务 {status}: {str(job.get('error') or '')[:500]}", item_id),
            )


async def _dispatch_pending() -> int:
    from app.core.jobs.service import enqueue_change_execute, enqueue_task

    dispatched = 0
    rows = await query(
        "SELECT id, user_id, kind, payload FROM night_queue "
        "WHERE status = 'pending' ORDER BY created_at ASC LIMIT %s",
        (settings.night_max_per_hour,),
    )
    for item_id, user_id, kind, payload in rows:
        payload = payload or {}
        try:
            if await _budget_exhausted(user_id):
                await execute(
                    "UPDATE night_queue SET status = 'failed', finished_at = now(), "
                    "error = '今日 token 预算已接近上限，为白天保留额度，未执行' WHERE id = %s",
                    (item_id,),
                )
                continue
            if kind == "change_execute":
                change_id = payload.get("change_id")
                rows2 = await query(
                    "SELECT status FROM change_requests WHERE id = %s AND user_id = %s",
                    (change_id, user_id),
                )
                if not rows2 or rows2[0][0] not in ("plan_approved", "failed"):
                    await execute(
                        "UPDATE night_queue SET status = 'failed', finished_at = now(), "
                        "error = '变更状态已变化（可能已执行过），跳过' WHERE id = %s",
                        (item_id,),
                    )
                    continue
                job_id = await enqueue_change_execute(str(change_id), user_id)
            else:
                import uuid as _uuid
                task_id = str(_uuid.uuid4())
                title = (payload.get("bug_report") or "").strip().splitlines()[0][:120]
                await execute(
                    "INSERT INTO tasks (id, user_id, repo_id, title, bug_report, status) "
                    "VALUES (%s, %s, %s, %s, %s, 'running')",
                    (task_id, user_id, payload.get("repo_id"), title,
                     payload.get("bug_report")),
                )
                job_id = await enqueue_task(task_id, user_id=user_id,
                                            idempotency_key=f"task:{task_id}")
                await execute(
                    "UPDATE tasks SET job_id = %s WHERE id = %s", (job_id, task_id)
                )
                await execute(
                    "UPDATE night_queue SET target_id = %s WHERE id = %s",
                    (task_id, item_id),
                )
            await execute(
                "UPDATE night_queue SET status = 'running', job_id = %s, "
                "started_at = now() WHERE id = %s",
                (job_id, item_id),
            )
            dispatched += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("night_queue_dispatch_failed", item=str(item_id), error=str(exc))
            await execute(
                "UPDATE night_queue SET status = 'failed', finished_at = now(), "
                "error = %s WHERE id = %s",
                (str(exc)[:500], item_id),
            )
    return dispatched


async def run_maintenance() -> dict:
    """Hourly entrypoint from the cleanup loop."""
    if not settings.night_queue_enabled:
        return {"dispatched": 0, "skipped": "disabled"}
    if not _in_window():
        return {"dispatched": 0, "skipped": "outside_window"}
    await _reconcile_running()
    dispatched = await _dispatch_pending()
    if dispatched:
        logger.info("night_queue_dispatched", count=dispatched)
    return {"dispatched": dispatched}

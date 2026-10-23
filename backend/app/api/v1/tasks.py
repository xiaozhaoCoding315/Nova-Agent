"""Task endpoints: red-green bug reproduction and fix."""
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException

from app.core.conflicts import ConflictError
from app.core.indexing.pipeline import get_repo
from app.core.jobs.service import enqueue_index, enqueue_task
from app.core.sandbox.runtime import sandbox_status
from app.core.security.auth import get_current_user
from app.core.review.service import review_task
from app.core.security.limits import check_job_quota, ensure_token_budget
from app.core.tasks.engine import apply_task_result
from app.db import execute, query
from app.models.schemas import TaskCreate

router = APIRouter()


async def _task_or_404(task_id: str, user_id: int) -> dict:
    rows = await query(
        """
        SELECT t.id, t.title, t.bug_report, t.status, t.steps, t.result,
               t.created_at, t.updated_at, t.repo_id, r.name, t.user_id, t.job_id
        FROM tasks t JOIN repos r ON r.id = t.repo_id
        WHERE t.id = %s AND t.user_id = %s
        """,
        (task_id, user_id),
    )
    if not rows:
        raise HTTPException(status_code=404, detail="任务不存在")
    r = rows[0]
    return {
        "id": str(r[0]), "title": r[1], "bug_report": r[2], "status": r[3],
        "steps": r[4] or [], "result": r[5] or {},
        "created_at": r[6], "updated_at": r[7],
        "repo_id": str(r[8]), "repo_name": r[9], "user_id": r[10],
        "job_id": str(r[11]) if r[11] else None,
    }


@router.post("/tasks")
async def create_task(body: TaskCreate, user: dict = Depends(get_current_user)):
    repo = await get_repo(body.repo_id, user["id"])
    if not repo:
        raise HTTPException(status_code=404, detail="仓库不存在")
    if repo["status"] != "ready":
        raise HTTPException(status_code=400, detail="仓库尚未完成索引，暂不能创建修复任务")

    status = await sandbox_status()
    if not status["available"]:
        raise HTTPException(status_code=400, detail=f"沙箱不可用：{status['reason']}")

    check_job_quota(user, "task")
    await ensure_token_budget(user)

    task_id = str(uuid.uuid4())
    title = (body.title or body.bug_report.strip().splitlines()[0])[:120]
    await execute(
        "INSERT INTO tasks (id, user_id, repo_id, title, bug_report, status) "
        "VALUES (%s, %s, %s, %s, %s, 'running')",
        (task_id, user["id"], body.repo_id, title, body.bug_report),
    )
    job_id = await enqueue_task(
        task_id, user_id=user["id"], idempotency_key=f"task:{task_id}"
    )
    await execute("UPDATE tasks SET job_id = %s WHERE id = %s", (job_id, task_id))
    return await _task_or_404(task_id, user["id"])


@router.get("/tasks")
async def list_tasks(user: dict = Depends(get_current_user)):
    rows = await query(
        """
        SELECT t.id, t.title, t.status, t.created_at, t.repo_id, r.name,
               COALESCE(t.result->>'applied', 'false')
        FROM tasks t JOIN repos r ON r.id = t.repo_id
        WHERE t.user_id = %s ORDER BY t.created_at DESC LIMIT 50
        """,
        (user["id"],),
    )
    return [
        {"id": str(r[0]), "title": r[1], "status": r[2], "created_at": r[3],
         "repo_id": str(r[4]), "repo_name": r[5], "applied": r[6] == "true"}
        for r in rows
    ]


@router.get("/tasks/{task_id}")
async def get_task(task_id: str, user: dict = Depends(get_current_user)):
    return await _task_or_404(task_id, user["id"])


@router.post("/tasks/{task_id}/review")
async def review_task_endpoint(task_id: str, user: dict = Depends(get_current_user)):
    task = await _task_or_404(task_id, user["id"])
    if task["status"] not in ("ready", "failed"):
        raise HTTPException(status_code=400, detail="只有已生成结果的修复任务才能审查")
    check_job_quota(user, "review")
    try:
        return await review_task(task)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"审查失败：{exc}")


@router.post("/tasks/{task_id}/apply")
async def apply_task(task_id: str, user: dict = Depends(get_current_user)):
    task = await _task_or_404(task_id, user["id"])
    if task["status"] != "ready":
        raise HTTPException(status_code=400, detail="只有验证通过（ready）的任务才能应用")
    check_job_quota(user, "reindex")
    try:
        applied = await apply_task_result({
            "id": task["id"], "repo_id": task["repo_id"],
            "user_id": user["id"], "result": task["result"],
        })
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await enqueue_index(task["repo_id"], reindex=True, user_id=user["id"])
    return {"ok": True, "applied": applied, "reindex_started": True}


@router.post("/tasks/{task_id}/reject")
async def reject_task(task_id: str, user: dict = Depends(get_current_user)):
    task = await _task_or_404(task_id, user["id"])
    if task["status"] != "ready":
        raise HTTPException(status_code=400, detail="只有 ready 状态的任务可以拒绝")
    result = task["result"] or {}
    result["rejected"] = True
    await execute(
        "UPDATE tasks SET status = 'rejected', result = %s, updated_at = now() WHERE id = %s",
        (json.dumps(result, ensure_ascii=False), task_id),
    )
    return {"ok": True}
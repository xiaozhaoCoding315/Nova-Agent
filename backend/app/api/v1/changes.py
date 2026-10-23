"""Change workflow endpoints: SPEC -> plan -> execute -> review -> apply."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.changes import service
from app.core.editing.service import apply_edit, reject_edit
from app.core.indexing.pipeline import get_repo
from app.core.jobs.runner import runner
from app.core.jobs.service import (
    enqueue_change_execute,
    enqueue_change_plan,
    enqueue_change_spec,
    enqueue_index,
)
from app.core.security.audit import AuditAction, log_audit
from app.core.security.auth import get_current_user
from app.core.security.limits import check_job_quota, ensure_token_budget
from app.models.schemas import (
    ChangeActionOut,
    ChangeApplyOut,
    ChangeApplyRequest,
    ChangeCreate,
    ChangeListItemOut,
    ChangeOut,
    ChangeReportOut,
    ChangeSpecUpdate,
    OkOut,
)

router = APIRouter()


async def _change_or_404(change_id: str, user: dict) -> dict:
    change = await service.get_change(change_id, user["id"])
    if not change:
        raise HTTPException(status_code=404, detail="变更不存在")
    return change


@router.post("/changes", response_model=ChangeOut)
async def create_change(body: ChangeCreate, user: dict = Depends(get_current_user)):
    repo = await get_repo(body.repo_id, user["id"])
    if not repo:
        raise HTTPException(status_code=404, detail="仓库不存在")
    if repo["status"] != "ready":
        raise HTTPException(status_code=400, detail="仓库尚未完成索引，不能创建变更")
    check_job_quota(user, "change")
    await ensure_token_budget(user)
    try:
        change = await service.create_change(
            user["id"], body.repo_id, body.requirements, body.title
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    job_id = await enqueue_change_spec(
        change["id"], user["id"], idempotency_key=f"change_spec:{change['id']}"
    )
    await service.set_change_job(change["id"], job_id)
    change["job_id"] = job_id
    return change


@router.get("/changes", response_model=list[ChangeListItemOut])
async def list_changes(
    limit: int = Query(50, ge=1, le=100),
    user: dict = Depends(get_current_user),
):
    return await service.list_changes(user["id"], limit)


@router.get("/changes/{change_id}", response_model=ChangeOut)
async def get_change(change_id: str, user: dict = Depends(get_current_user)):
    return await _change_or_404(change_id, user)


@router.patch("/changes/{change_id}", response_model=ChangeOut)
async def update_change(
    change_id: str,
    body: ChangeSpecUpdate,
    user: dict = Depends(get_current_user),
):
    try:
        return await service.update_spec(
            change_id, user["id"], body.model_dump(exclude_none=True)
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/changes/{change_id}/draft", response_model=ChangeActionOut)
async def redraft_change(change_id: str, user: dict = Depends(get_current_user)):
    change = await _change_or_404(change_id, user)
    if change["status"] not in ("draft", "failed"):
        raise HTTPException(status_code=400, detail="只有草稿状态可以重新起草 SPEC")
    check_job_quota(user, "change")
    await ensure_token_budget(user)
    job_id = await enqueue_change_spec(change_id, user["id"])
    await service.set_change_job(change_id, job_id)
    return {"ok": True, "job_id": job_id}


@router.post("/changes/{change_id}/approve", response_model=ChangeOut)
async def approve_change(change_id: str, user: dict = Depends(get_current_user)):
    try:
        return await service.approve_spec(change_id, user["id"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/changes/{change_id}/plan", response_model=ChangeActionOut)
async def plan_change(change_id: str, user: dict = Depends(get_current_user)):
    change = await _change_or_404(change_id, user)
    if change["status"] not in ("approved", "failed"):
        raise HTTPException(status_code=400, detail="请先冻结 SPEC")
    check_job_quota(user, "change")
    await ensure_token_budget(user)
    job_id = await enqueue_change_plan(change_id, user["id"])
    await service.set_change_job(change_id, job_id)
    return {"ok": True, "job_id": job_id}


@router.post("/changes/{change_id}/plan/approve", response_model=ChangeOut)
async def approve_change_plan(change_id: str, user: dict = Depends(get_current_user)):
    try:
        return await service.approve_plan(change_id, user["id"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/changes/{change_id}/execute", response_model=ChangeActionOut)
async def execute_change(change_id: str, user: dict = Depends(get_current_user)):
    change = await _change_or_404(change_id, user)
    if change["status"] not in ("plan_approved", "failed"):
        raise HTTPException(status_code=400, detail="计划尚未批准，不能执行")
    check_job_quota(user, "change")
    await ensure_token_budget(user)
    job_id = await enqueue_change_execute(change_id, user["id"])
    await service.set_change_job(change_id, job_id)
    return {"ok": True, "job_id": job_id}


@router.post("/changes/{change_id}/apply", response_model=ChangeApplyOut)
async def apply_change(
    change_id: str,
    body: ChangeApplyRequest | None = None,
    user: dict = Depends(get_current_user),
):
    change = await _change_or_404(change_id, user)
    if change["status"] != "review":
        raise HTTPException(status_code=400, detail="当前没有待审批的变更提案")
    proposal = change.get("proposal") or {}
    edit_id = proposal.get("edit_id")
    if not edit_id:
        raise HTTPException(status_code=400, detail="提案缺少编辑记录")
    review = proposal.get("review") or {}
    if review.get("verdict") == "block" and not (body and body.force):
        raise HTTPException(status_code=400, detail="只读审查判定为 block，不能直接应用；请先修复或强制应用")
    try:
        applied = await apply_edit(edit_id, user["id"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    evidence = change.get("evidence") or {}
    evidence.update({
        "applied": True,
        "applied_at": datetime.now(timezone.utc).isoformat(),
        "commit": applied.get("commit"),
        "applied_files": applied.get("applied") or [],
    })
    await service.set_evidence(change_id, evidence)
    await service.set_change_status(change_id, "applied", error=None)
    await log_audit(
        AuditAction.CHANGE_APPLIED,
        user_id=str(user["id"]),
        details={
            "change_id": change_id, "repo_id": change["repo_id"],
            "files": applied.get("applied") or [], "commit": applied.get("commit"),
        },
    )
    await enqueue_index(change["repo_id"], reindex=True, user_id=user["id"])
    return {"ok": True, "applied": applied.get("applied") or [], "commit": applied.get("commit")}


@router.post("/changes/{change_id}/reject", response_model=OkOut)
async def reject_change(change_id: str, user: dict = Depends(get_current_user)):
    change = await _change_or_404(change_id, user)
    if change["status"] not in ("review", "plan_ready", "plan_approved"):
        raise HTTPException(status_code=400, detail="当前状态不能拒绝")
    proposal = change.get("proposal") or {}
    if proposal.get("edit_id"):
        try:
            await reject_edit(proposal["edit_id"], user["id"])
        except ValueError:
            pass
    await service.set_change_status(change_id, "rejected", error=None)
    return {"ok": True}


@router.post("/changes/{change_id}/cancel", response_model=OkOut)
async def cancel_change(change_id: str, user: dict = Depends(get_current_user)):
    change = await _change_or_404(change_id, user)
    if change["status"] not in ("drafting", "planning", "executing"):
        raise HTTPException(status_code=400, detail="当前状态没有可取消的后台任务")
    if change.get("job_id"):
        await runner.cancel(change["job_id"], user["id"])
    await service.set_change_status(change_id, "canceled", error="用户取消")
    return {"ok": True}


@router.get("/changes/{change_id}/report", response_model=ChangeReportOut)
async def change_report(change_id: str, user: dict = Depends(get_current_user)):
    change = await _change_or_404(change_id, user)
    return {
        "change_id": change_id,
        "status": change["status"],
        "spec": {
            "title": change["title"],
            "goal": change["goal"],
            "acceptance_cases": change["acceptance_cases"],
            "in_scope": change["in_scope"],
            "out_scope": change["out_scope"],
        },
        "tasks": change["tasks"],
        "proposal": change.get("proposal") or {},
        "evidence": change.get("evidence") or {},
        "error": change.get("error"),
    }

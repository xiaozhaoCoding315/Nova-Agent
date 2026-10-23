"""Background job endpoints: list / inspect / cancel / retry."""
from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.jobs.runner import runner
from app.core.security.auth import get_current_user
from app.models.schemas import JobOut

router = APIRouter()


@router.get("/jobs", response_model=list[JobOut])
async def list_jobs(
    limit: int = Query(30, ge=1, le=100),
    user: dict = Depends(get_current_user),
):
    return await runner.list(user["id"], limit)


@router.get("/jobs/{job_id}", response_model=JobOut)
async def get_job(job_id: str, user: dict = Depends(get_current_user)):
    job = await runner.get(job_id, user["id"])
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    return job


@router.post("/jobs/{job_id}/cancel", response_model=JobOut)
async def cancel_job(job_id: str, user: dict = Depends(get_current_user)):
    job = await runner.cancel(job_id, user["id"])
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    return job


@router.post("/jobs/{job_id}/retry", response_model=JobOut)
async def retry_job(job_id: str, user: dict = Depends(get_current_user)):
    job = await runner.get(job_id, user["id"])
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    if job["status"] not in ("failed", "canceled"):
        raise HTTPException(status_code=400, detail="只有失败或已取消的任务可以重试")
    return await runner.retry(job_id, user["id"])

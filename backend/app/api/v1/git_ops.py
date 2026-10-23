"""Git delivery endpoints: status / init / commit / diff / rollback / export."""
import asyncio
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse

from app.core.git_ops.service import (
    commit,
    diff,
    export_zip,
    init_repo,
    rollback,
    status,
)
from app.core.indexing.pipeline import get_repo
from app.core.jobs.service import enqueue_index
from app.core.security.auth import get_current_user
from app.core.security.limits import check_job_quota
from app.models.schemas import (
    GitCommitRequest,
    GitDiffOut,
    GitRollbackOut,
    GitRollbackRequest,
    GitStatusOut,
)

router = APIRouter()


async def _repo_or_404(repo_id: str, user_id: int) -> dict:
    repo = await get_repo(repo_id, user_id)
    if not repo:
        raise HTTPException(status_code=404, detail="仓库不存在")
    return repo


@router.get("/repos/{repo_id}/git", response_model=GitStatusOut)
async def git_status(repo_id: str, user: dict = Depends(get_current_user)):
    repo = await _repo_or_404(repo_id, user["id"])
    return await status(Path(repo["root_path"]))


@router.post("/repos/{repo_id}/git/init", response_model=GitStatusOut)
async def git_init(repo_id: str, user: dict = Depends(get_current_user)):
    repo = await _repo_or_404(repo_id, user["id"])
    try:
        return await init_repo(Path(repo["root_path"]))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/repos/{repo_id}/git/commit", response_model=GitStatusOut)
async def git_commit(
    repo_id: str,
    body: GitCommitRequest | None = None,
    user: dict = Depends(get_current_user),
):
    repo = await _repo_or_404(repo_id, user["id"])
    try:
        info = await commit(Path(repo["root_path"]), body.message if body else None)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return info


@router.get("/repos/{repo_id}/git/diff", response_model=GitDiffOut)
async def git_diff(repo_id: str, user: dict = Depends(get_current_user)):
    repo = await _repo_or_404(repo_id, user["id"])
    return {"diff": await diff(Path(repo["root_path"]))}


@router.post("/repos/{repo_id}/git/rollback", response_model=GitRollbackOut)
async def git_rollback(
    repo_id: str,
    body: GitRollbackRequest,
    user: dict = Depends(get_current_user),
):
    repo = await _repo_or_404(repo_id, user["id"])
    check_job_quota(user, "reindex")
    try:
        info = await rollback(Path(repo["root_path"]), body.commit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await enqueue_index(repo_id, reindex=True, user_id=user["id"])
    return {**info, "reindex_started": True}


@router.get("/repos/{repo_id}/export")
async def export_repo(
    repo_id: str,
    background: BackgroundTasks,
    user: dict = Depends(get_current_user),
):
    repo = await _repo_or_404(repo_id, user["id"])
    try:
        zip_path = await asyncio.to_thread(export_zip, Path(repo["root_path"]))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"导出失败：{exc}")
    background.add_task(lambda: zip_path.unlink(missing_ok=True))
    safe_name = "".join(ch for ch in repo["name"] if ch.isalnum() or ch in "-_") or "repo"
    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=f"{safe_name}.zip",
    )
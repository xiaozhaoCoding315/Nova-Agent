"""Preview deployment endpoints (admin-only)."""
from fastapi import APIRouter, Depends, HTTPException

from app.core.deploy.service import (
    DeployError,
    deploy_preview,
    get_deployment,
    list_deployments,
    teardown_preview,
)
from app.core.security.auth import require_admin
from app.core.security.limits import check_job_quota
from app.models.schemas import DeployRequest, DeploymentOut

router = APIRouter()


@router.post("/repos/{repo_id}/deploy", response_model=DeploymentOut)
async def deploy_repo(
    repo_id: str,
    body: DeployRequest | None = None,
    user: dict = Depends(require_admin),
):
    check_job_quota(user, "deploy")
    try:
        return await deploy_preview(user, repo_id, force=bool(body and body.force))
    except DeployError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/repos/{repo_id}/deployments", response_model=list[DeploymentOut])
async def repo_deployments(repo_id: str, user: dict = Depends(require_admin)):
    return await list_deployments(user["id"], repo_id=repo_id)


@router.get("/deploys/{deploy_id}", response_model=DeploymentOut)
async def get_deploy(deploy_id: str, user: dict = Depends(require_admin)):
    deployment = await get_deployment(deploy_id, user["id"])
    if not deployment:
        raise HTTPException(status_code=404, detail="预览不存在")
    return deployment


@router.post("/deploys/{deploy_id}/teardown", response_model=DeploymentOut)
async def teardown_deploy(deploy_id: str, user: dict = Depends(require_admin)):
    try:
        return await teardown_preview(user, deploy_id)
    except DeployError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

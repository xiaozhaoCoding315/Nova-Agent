"""Preview deployment endpoints (admin-only, server mode only)."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.routing import APIRoute

from app.config import settings
from app.core.deploy.service import (
    DeployError,
    deploy_preview,
    get_deployment,
    list_deployments,
    teardown_preview,
)
from app.core.indexing.pipeline import get_repo
from app.core.security.auth import require_admin
from app.core.security.limits import check_job_quota
from app.models.schemas import DeployRequest, DeploymentOut


def require_server_mode() -> None:
    """Preview deployment needs Docker; local mode never exposes it."""
    if settings.is_local:
        raise HTTPException(status_code=404, detail="本地模式不提供预览部署")


class _ServerModeRoute(APIRoute):
    """Reject local mode before FastAPI reads the body or resolves auth."""

    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            require_server_mode()
            return await original(request)

        return handler


router = APIRouter(
    route_class=_ServerModeRoute,
    dependencies=[Depends(require_server_mode)],
)


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
    if not await get_repo(repo_id, user["id"]):
        raise HTTPException(status_code=404, detail="仓库不存在或无权访问")
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

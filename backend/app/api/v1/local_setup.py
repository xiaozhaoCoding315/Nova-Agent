"""First-run local setup: register a folder and save an encrypted LLM key."""
from fastapi import APIRouter, Depends, HTTPException

from app.config import settings
from app.core.llm.user_settings import save_user_config
from app.core.security.audit import AuditAction, log_audit
from app.core.security.auth import get_current_user
from app.local.projects import register_local_project, validate_local_project_path
from app.db import query
from app.models.schemas import (
    LocalSetupIn,
    LocalSetupResultOut,
    LocalSetupStatusOut,
)

router = APIRouter()


def require_local_mode() -> None:
    if not settings.is_local:
        raise HTTPException(status_code=404, detail="仅本地模式提供首次启动接口")


@router.get("/local/setup", response_model=LocalSetupStatusOut)
async def get_local_setup(user: dict = Depends(get_current_user)):
    require_local_mode()
    repo_rows = await query(
        "SELECT count(*) FROM repos WHERE user_id = %s", (user["id"],)
    )
    cred_rows = await query(
        "SELECT provider, model, api_key_enc, is_default FROM user_llm_providers "
        "WHERE user_id = %s ORDER BY is_default DESC, updated_at DESC",
        (user["id"],),
    )
    project_count = int(repo_rows[0][0] or 0) if repo_rows else 0
    has_key = any(str(row[2] or "") for row in cred_rows)
    default = next((row for row in cred_rows if row[3]), cred_rows[0] if cred_rows else None)
    return LocalSetupStatusOut(
        configured=project_count > 0 and has_key,
        data_dir=str(settings.data_root),
        project_count=project_count,
        has_llm_key=has_key,
        default_provider=default[0] if default else None,
        default_model=default[1] if default else None,
    )


@router.post("/local/setup", response_model=LocalSetupResultOut)
async def run_local_setup(
    body: LocalSetupIn, user: dict = Depends(get_current_user)
):
    require_local_mode()
    if not body.api_key:
        existing = await query(
            "SELECT 1 FROM user_llm_providers "
            "WHERE user_id = %s AND api_key_enc <> '' LIMIT 1",
            (user["id"],),
        )
        if not existing:
            raise HTTPException(status_code=400, detail="首次启动请填写 API Key")
    try:
        validate_local_project_path(body.project_path, settings.data_root)
        # api_key=None makes save_user_config keep the credential already
        # stored for this provider instead of overwriting it with an empty key.
        await save_user_config(
            user["id"],
            provider=body.provider,
            model=body.model,
            api_key=body.api_key,
            is_default=True,
        )
        repo = await register_local_project(
            user, body.project_path, body.project_name
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await log_audit(
        AuditAction.REPO_IMPORT,
        user_id=str(user["id"]),
        details={"repo_id": repo["id"], "source": "local_setup"},
    )
    return LocalSetupResultOut(
        ok=True,
        repo=repo,
        provider=body.provider,
        model=body.model,
        has_key=True,
    )

"""Contract status endpoints for a workspace."""
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from app.core.contracts.service import contract_step_name, discover_contract_from_root
from app.core.indexing.pipeline import get_repo
from app.core.security.auth import get_current_user
from app.db import query
from app.models.schemas import ContractStatusOut

router = APIRouter()


@router.get("/repos/{repo_id}/contract", response_model=ContractStatusOut)
async def contract_status(repo_id: str, user: dict = Depends(get_current_user)):
    repo = await get_repo(repo_id, user["id"])
    if not repo:
        raise HTTPException(status_code=404, detail="仓库不存在")

    info = discover_contract_from_root(Path(repo["root_path"]))
    rows = await query("SELECT last_check FROM repos WHERE id = %s", (repo_id,))
    last = (rows[0][0] if rows else None) or {}
    step = next(
        (item for item in (last.get("steps") or []) if item.get("name") == contract_step_name()),
        None,
    )
    detail = ""
    if step:
        detail = (step.get("stderr") or step.get("stdout") or "")[-1500:]
    return {
        **info,
        "last_status": step.get("status") if step else None,
        "last_detail": detail,
        "checked_at": last.get("at"),
    }

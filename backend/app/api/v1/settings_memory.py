"""User memory policy: automatic learning, retention and scope overrides."""
from fastapi import APIRouter, Depends, HTTPException

from app.core.memory import policy as policy_mod
from app.core.security.audit import log_audit
from app.core.security.auth import get_current_user
from app.models.schemas import MemorySettingsOut, MemorySettingsUpdate

router = APIRouter()


@router.get("/settings/memory", response_model=MemorySettingsOut)
async def get_memory_settings(user: dict = Depends(get_current_user)):
    return policy_mod.to_dict(await policy_mod.get_policy(user["id"]))


@router.put("/settings/memory", response_model=MemorySettingsOut)
async def update_memory_settings(
    body: MemorySettingsUpdate, user: dict = Depends(get_current_user),
):
    values = {
        key: getattr(body, key) for key in body.model_fields_set
    }
    if not values:
        raise HTTPException(status_code=400, detail="没有需要修改的记忆设置")
    try:
        updated = await policy_mod.update_policy(user["id"], values)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await log_audit(
        "memory_settings_update", user_id=str(user["id"]),
        details={"keys": sorted(values)},
    )
    return policy_mod.to_dict(updated)

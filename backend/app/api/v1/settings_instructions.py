"""Layered human instructions: org policy, user instructions and project rules."""
from fastapi import APIRouter, Depends, HTTPException

from app.core.memory import instructions as instructions_mod
from app.core.security.audit import log_audit
from app.core.security.auth import get_current_user
from app.models.schemas import InstructionCreate, InstructionOut, InstructionUpdate, OkOut

router = APIRouter()


@router.get("/settings/instructions", response_model=list[InstructionOut])
async def list_instructions(
    level: str | None = None, user: dict = Depends(get_current_user),
):
    try:
        return await instructions_mod.list_instructions(user["id"], level=level)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/settings/instructions", response_model=InstructionOut)
async def create_instruction(
    body: InstructionCreate, user: dict = Depends(get_current_user),
):
    values = body.model_dump()
    try:
        created = await instructions_mod.create_instruction(user["id"], values)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await log_audit(
        "instruction_create", user_id=str(user["id"]),
        details={
            "id": created["id"], "level": created["level"],
            "scope": f"{created['scope_type']}:{created['scope_id']}",
        },
    )
    return created


@router.put("/settings/instructions/{instruction_id}", response_model=InstructionOut)
async def update_instruction(
    instruction_id: int,
    body: InstructionUpdate,
    user: dict = Depends(get_current_user),
):
    values = {key: getattr(body, key) for key in body.model_fields_set}
    if not values:
        raise HTTPException(status_code=400, detail="没有需要修改的指令字段")
    try:
        updated = await instructions_mod.update_instruction(
            user["id"], instruction_id, values,
        )
    except instructions_mod.InstructionNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await log_audit(
        "instruction_update", user_id=str(user["id"]),
        details={"id": instruction_id, "keys": sorted(values)},
    )
    return updated


@router.delete("/settings/instructions/{instruction_id}", response_model=OkOut)
async def delete_instruction(
    instruction_id: int, user: dict = Depends(get_current_user),
):
    removed = await instructions_mod.delete_instruction(user["id"], instruction_id)
    if not removed:
        raise HTTPException(status_code=404, detail="指令不存在")
    await log_audit(
        "instruction_delete", user_id=str(user["id"]),
        details={"id": instruction_id},
    )
    return {"ok": True}

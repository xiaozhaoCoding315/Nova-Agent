"""Admin user management."""
from fastapi import APIRouter, Depends, HTTPException

from app.core.security.accounts import (
    admin_delete_user,
    admin_reset_password,
    admin_set_user_fields,
    create_user,
    list_users,
)
from app.core.security.audit import log_audit
from app.core.security.auth import require_admin
from app.models.schemas import (
    AdminPasswordResetRequest,
    AdminUserCreateRequest,
    AdminUserUpdateRequest,
    OkOut,
    UserOut,
)

router = APIRouter()


@router.get("/admin/users", response_model=list[UserOut])
async def admin_list_users(user: dict = Depends(require_admin)):
    return await list_users()


@router.post("/admin/users", response_model=UserOut)
async def admin_create_user(body: AdminUserCreateRequest, user: dict = Depends(require_admin)):
    try:
        created = await create_user(
            body.username,
            body.password,
            display_name=body.display_name or "",
            role=body.role,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await log_audit("admin_user_create", user_id=str(user["id"]),
                    details={"target": created["id"], "username": created["username"]})
    return created


@router.patch("/admin/users/{user_id}", response_model=UserOut)
async def admin_update_user(
    user_id: int,
    body: AdminUserUpdateRequest,
    user: dict = Depends(require_admin),
):
    if user_id == user["id"] and (
        body.status == "disabled" or body.role == "demo"
    ):
        raise HTTPException(status_code=400, detail="不能禁用或降级当前登录的管理员")
    try:
        updated = await admin_set_user_fields(
            user_id,
            status=body.status,
            role=body.role,
            display_name=body.display_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await log_audit("admin_user_update", user_id=str(user["id"]),
                    details={"target": user_id, "status": body.status, "role": body.role},
                    risk_level="warn")
    return updated


@router.post("/admin/users/{user_id}/password", response_model=OkOut)
async def admin_reset_user_password(
    user_id: int,
    body: AdminPasswordResetRequest,
    user: dict = Depends(require_admin),
):
    try:
        await admin_reset_password(user_id, body.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await log_audit("admin_password_reset", user_id=str(user["id"]),
                    details={"target": user_id}, risk_level="warn")
    return {"ok": True}


@router.delete("/admin/users/{user_id}", response_model=OkOut)
async def admin_delete_user_endpoint(user_id: int, user: dict = Depends(require_admin)):
    if user_id == user["id"]:
        raise HTTPException(status_code=400, detail="不能删除当前登录的账号")
    try:
        from app.core.account_cleanup import purge_user_resources
        from app.core.security.accounts import assert_user_deletable
        await assert_user_deletable(user_id)
        await purge_user_resources(user_id)
        await admin_delete_user(user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await log_audit("admin_user_delete", user_id=str(user["id"]),
                    details={"target": user_id}, risk_level="warn")
    return {"ok": True}

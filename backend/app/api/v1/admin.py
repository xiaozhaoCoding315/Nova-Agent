"""Admin user management."""
from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.security.accounts import (
    admin_delete_user,
    admin_reset_password,
    admin_set_user_fields,
    create_invite,
    create_user,
    delete_invite,
    list_invites,
    list_users_with_usage,
)
from app.core.security.audit import log_audit
from app.core.security.auth import require_admin
from app.db import query
from app.models.schemas import (
    AdminPasswordResetRequest,
    AdminUserCreateRequest,
    AdminUserOut,
    AdminUserUpdateRequest,
    InviteCodeCreateRequest,
    InviteCodeOut,
    OkOut,
    SourceUsageOut,
    UserOut,
)

router = APIRouter()


@router.get("/admin/usage/sources", response_model=list[SourceUsageOut])
async def admin_usage_sources(
    days: int = Query(7, ge=1, le=90),
    user: dict = Depends(require_admin),
):
    """Token spend grouped by call source and model for cost attribution."""
    rows = await query(
        """
        SELECT source, COALESCE(model, ''), COUNT(*),
               COALESCE(SUM(prompt_tokens + completion_tokens), 0)
        FROM usage_log
        WHERE created_at >= now() - (%s * interval '1 day')
        GROUP BY source, COALESCE(model, '')
        ORDER BY 4 DESC
        """,
        (days,),
    )
    return [
        SourceUsageOut(source=r[0], model=r[1], calls=int(r[2]), tokens=int(r[3]))
        for r in rows
    ]


@router.get("/admin/users", response_model=list[AdminUserOut])
async def admin_list_users(user: dict = Depends(require_admin)):
    return await list_users_with_usage()


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


@router.patch("/admin/users/{user_id}", response_model=AdminUserOut)
async def admin_update_user(
    user_id: int,
    body: AdminUserUpdateRequest,
    user: dict = Depends(require_admin),
):
    if user_id == user["id"] and (
        body.status == "disabled" or body.role == "demo"
    ):
        raise HTTPException(status_code=400, detail="不能禁用或降级当前登录的管理员")
    quota_keys = (
        "quota_daily_tokens", "quota_hourly_messages", "quota_sandbox_daily",
        "quota_job_hourly", "quota_storage_mb",
    )
    sent = body.model_fields_set
    quotas = {key: getattr(body, key) for key in quota_keys if key in sent}
    try:
        updated = await admin_set_user_fields(
            user_id,
            status=body.status,
            role=body.role,
            display_name=body.display_name,
            quotas=quotas,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await log_audit("admin_user_update", user_id=str(user["id"]),
                    details={"target": user_id, "status": body.status, "role": body.role,
                             **{f"quota:{k}": v for k, v in quotas.items()}},
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


# ---------------------------------------------------------------------------
# 邀请码（注册收紧：只有持有有效邀请码的访客能注册正式账号）
# ---------------------------------------------------------------------------


@router.get("/admin/invites", response_model=list[InviteCodeOut])
async def admin_list_invites(user: dict = Depends(require_admin)):
    return await list_invites()


@router.post("/admin/invites", response_model=InviteCodeOut)
async def admin_create_invite(
    body: InviteCodeCreateRequest,
    user: dict = Depends(require_admin),
):
    try:
        invite = await create_invite(
            note=body.note,
            max_uses=body.max_uses,
            expires_days=body.expires_days or None,
            created_by=user["id"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await log_audit("invite_create", user_id=str(user["id"]), details={"note": body.note})
    return invite


@router.delete("/admin/invites/{invite_id}", response_model=OkOut)
async def admin_delete_invite(invite_id: int, user: dict = Depends(require_admin)):
    removed = await delete_invite(invite_id)
    if not removed:
        raise HTTPException(status_code=404, detail="邀请码不存在")
    await log_audit("invite_delete", user_id=str(user["id"]), details={"invite_id": invite_id})
    return {"ok": True}

"""Auth endpoints: login, registration, guest trial, profile and password."""
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.config import settings
from app.core.security.accounts import (
    change_password,
    create_guest_user,
    create_user,
    generate_recovery_code,
    reset_password_with_recovery,
    touch_login,
    update_profile,
)
from app.core.security.audit import AuditAction, log_audit
from app.core.security.auth import (
    COOKIE_NAME,
    authenticate,
    create_token,
    get_current_user,
)
from app.models.schemas import (
    AuthConfigOut,
    LoginRequest,
    OkOut,
    PasswordChangeRequest,
    PasswordResetRequest,
    ProfileUpdateRequest,
    RegisterOut,
    RegisterRequest,
    UserOut,
)

router = APIRouter()

_REG_WINDOW = 3600
_reg_buckets: dict[str, deque] = defaultdict(deque)


def _check_registration_rate(request: Request) -> None:
    limit = settings.max_registrations_per_hour
    if limit <= 0:
        return
    ip = request.client.host if request.client else "unknown"
    now = time.time()
    bucket = _reg_buckets[ip]
    while bucket and now - bucket[0] > _REG_WINDOW:
        bucket.popleft()
    if len(bucket) >= limit:
        raise HTTPException(status_code=429, detail="注册过于频繁，请稍后再试")
    bucket.append(now)


def _set_cookie(response: Response, user: dict) -> None:
    response.set_cookie(
        COOKIE_NAME,
        create_token(user),
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=settings.token_ttl_days * 86400,
        path="/",
    )


@router.get("/auth/config", response_model=AuthConfigOut)
async def auth_config():
    return AuthConfigOut(
        registration_mode=settings.registration_mode,
        guest_enabled=settings.guest_enabled,
        invite_required=settings.registration_mode == "invite",
        min_password_length=settings.min_password_length,
    )


@router.post("/auth/login", response_model=UserOut)
async def login(body: LoginRequest, response: Response):
    user = await authenticate(body.username, body.password)
    if not user:
        await log_audit(
            AuditAction.LOGIN_FAILED,
            details={"username": body.username},
            risk_level="warn",
        )
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    _set_cookie(response, user)
    await touch_login(user["id"])
    await log_audit(AuditAction.LOGIN, user_id=str(user["id"]), details={"username": user["username"]})
    return user


@router.post("/auth/register", response_model=RegisterOut)
async def register(body: RegisterRequest, request: Request, response: Response):
    mode = settings.registration_mode
    if mode == "closed":
        raise HTTPException(status_code=403, detail="当前部署未开放注册")
    if mode == "invite":
        if not settings.registration_invite_code:
            raise HTTPException(status_code=503, detail="未配置邀请码，请联系管理员")
        if (body.invite_code or "").strip() != settings.registration_invite_code:
            raise HTTPException(status_code=403, detail="邀请码不正确")
    _check_registration_rate(request)

    recovery_code = generate_recovery_code()
    try:
        user = await create_user(
            body.username,
            body.password,
            display_name=body.display_name or "",
            role="demo",
            recovery_code=recovery_code,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    _set_cookie(response, user)
    await log_audit("register", user_id=str(user["id"]), details={"username": user["username"]})
    return RegisterOut(user=user, recovery_code=recovery_code)


@router.post("/auth/guest", response_model=UserOut)
async def guest(request: Request, response: Response):
    if not settings.guest_enabled:
        raise HTTPException(status_code=403, detail="当前部署未开放游客体验")
    _check_registration_rate(request)
    try:
        user, _password = await create_guest_user()
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    _set_cookie(response, user)
    await log_audit("guest_create", user_id=str(user["id"]), details={"username": user["username"]})
    return user


@router.post("/auth/logout", response_model=OkOut)
async def logout(response: Response):
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/auth/me", response_model=UserOut)
async def me(user: dict = Depends(get_current_user)):
    return user


@router.patch("/auth/profile", response_model=UserOut)
async def update_my_profile(body: ProfileUpdateRequest, user: dict = Depends(get_current_user)):
    try:
        updated = await update_profile(user["id"], body.display_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return updated


@router.post("/auth/password", response_model=UserOut)
async def update_my_password(
    body: PasswordChangeRequest,
    response: Response,
    user: dict = Depends(get_current_user),
):
    try:
        updated = await change_password(user["id"], body.current_password, body.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _set_cookie(response, updated)
    await log_audit("password_change", user_id=str(user["id"]), risk_level="warn")
    return updated


@router.post("/auth/password/reset", response_model=OkOut)
async def reset_password(body: PasswordResetRequest):
    try:
        await reset_password_with_recovery(body.username, body.recovery_code, body.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await log_audit("password_reset", details={"username": body.username}, risk_level="warn")
    return {"ok": True}

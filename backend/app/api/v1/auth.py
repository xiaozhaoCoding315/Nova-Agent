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
    register_with_invite,
    request_email_code,
    reset_password_with_email_code,
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
from app.core.security.mailer import mask_email, send_verification_code
from app.db import query
from app.models.schemas import (
    AuthConfigOut,
    EmailCodeRequest,
    EmailResetRequest,
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

# 游客体验标记：签发一次、长期有效，防止同一浏览器反复薅游客额度
GUEST_USED_COOKIE = "nova_guest_used"
_GUEST_COOKIE_MAX_AGE = 365 * 86400


def _client_ip(request: Request) -> str:
    """取真实来源 IP：优先反代头（Caddy/Nginx），否则直连地址。"""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    return (request.headers.get("x-real-ip") or "").strip()[:64] or (
        request.client.host if request.client else "unknown"
    )


def _check_registration_rate(request: Request) -> None:
    limit = settings.max_registrations_per_hour
    if limit <= 0:
        return
    ip = _client_ip(request)
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
        email_verification=settings.email_enabled and settings.email_verify_required,
    )


@router.post("/auth/email/code", response_model=dict)
async def email_code(body: EmailCodeRequest, request: Request):
    """发送邮箱验证码（注册 / 找回密码）。邮件服务未配置时明确报 503。"""
    if not settings.email_enabled:
        raise HTTPException(status_code=503, detail="邮件服务未配置，请联系管理员")
    _check_registration_rate(request)
    try:
        code = await request_email_code(body.email, body.purpose)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    try:
        await send_verification_code(body.email.strip().lower(), code, body.purpose)
    except Exception as exc:  # noqa: BLE001 — SMTP 失败要给用户明确反馈
        await log_audit("email_code_send_failed", details={"error": str(exc)[:200]})
        raise HTTPException(status_code=502, detail="验证码邮件发送失败，请稍后重试或联系管理员")
    await log_audit("email_code_sent", details={"purpose": body.purpose})
    return {"ok": True, "masked_email": mask_email(body.email.strip().lower())}


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
    _check_registration_rate(request)
    ip = _client_ip(request)
    recovery_code = generate_recovery_code()
    email_required = settings.email_enabled and settings.email_verify_required

    # 邮箱验证开启时，先做快速前置校验（格式 / 是否已被占用），避免建号后回删
    if email_required:
        from app.core.security.accounts import email_taken, validate_email
        try:
            clean_email = validate_email(body.email)
            if await email_taken(clean_email):
                raise HTTPException(status_code=400, detail="该邮箱已被注册")
            if not (body.email_code or "").strip():
                raise HTTPException(status_code=400, detail="请输入邮箱验证码")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    if mode == "invite":
        provided = (body.invite_code or "").strip()
        static_code = settings.registration_invite_code
        if not static_code and not provided:
            raise HTTPException(status_code=503, detail="未配置邀请码，请联系管理员获取")
        try:
            if static_code and provided == static_code:
                # 兼容：部署方在 .env 配置的静态邀请码
                user = await create_user(
                    body.username,
                    body.password,
                    display_name=body.display_name or "",
                    role="demo",
                    recovery_code=recovery_code,
                    created_ip=ip,
                )
            else:
                user = await register_with_invite(
                    body.username,
                    body.password,
                    display_name=body.display_name or "",
                    invite_code=provided,
                    recovery_code=recovery_code,
                    created_ip=ip,
                )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    else:
        try:
            user = await create_user(
                body.username,
                body.password,
                display_name=body.display_name or "",
                role="demo",
                recovery_code=recovery_code,
                created_ip=ip,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    if email_required:
        from app.core.security.accounts import bind_email_after_register
        try:
            await bind_email_after_register(user, clean_email, body.email_code or "")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    _set_cookie(response, user)
    await log_audit("register", user_id=str(user["id"]), details={"username": user["username"]})
    return RegisterOut(user=user, recovery_code=recovery_code)


@router.post("/auth/guest", response_model=UserOut)
async def guest(request: Request, response: Response):
    if not settings.guest_enabled:
        raise HTTPException(status_code=403, detail="当前部署未开放游客体验")

    # 每台设备只允许体验一次：浏览器长期 cookie 标记
    if request.cookies.get(GUEST_USED_COOKIE):
        raise HTTPException(
            status_code=403,
            detail="这台设备已经体验过游客模式了。注册账号即可继续使用全部功能。",
        )
    # 服务端兜底：同一 IP 在窗口期内只允许创建一次游客
    ip = _client_ip(request)
    if settings.guest_once_ip_days > 0:
        rows = await query(
            "SELECT 1 FROM users WHERE is_guest AND created_ip = %s "
            "AND created_at > now() - (%s * interval '1 day') LIMIT 1",
            (ip, settings.guest_once_ip_days),
        )
        if rows:
            raise HTTPException(
                status_code=403,
                detail="该网络已经体验过游客模式了。注册账号即可继续使用全部功能。",
            )

    _check_registration_rate(request)
    try:
        user, _password = await create_guest_user(ip=ip)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    _set_cookie(response, user)
    response.set_cookie(
        GUEST_USED_COOKIE,
        "1",
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=_GUEST_COOKIE_MAX_AGE,
        path="/",
    )
    await log_audit(
        "guest_create", user_id=str(user["id"]),
        details={"username": user["username"], "ip": ip},
    )
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


@router.post("/auth/password/reset/email", response_model=OkOut)
async def reset_password_by_email(body: EmailResetRequest):
    """用户名 + 邮箱验证码找回密码（邮箱须与账号绑定一致）。"""
    if not settings.email_enabled:
        raise HTTPException(status_code=503, detail="邮件服务未配置，请联系管理员")
    try:
        await reset_password_with_email_code(body.username, body.email, body.code, body.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await log_audit("password_reset_email", details={"username": body.username}, risk_level="warn")
    return {"ok": True}

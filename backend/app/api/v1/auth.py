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
# 登录限流与注册分开计数：注册窗口只关心「建了多少号」，登录关心「试了多少次」。
_login_ip_buckets: dict[str, deque] = defaultdict(deque)
_login_user_buckets: dict[str, deque] = defaultdict(deque)

# 游客体验标记：签发一次、长期有效，防止同一浏览器反复薅游客额度
GUEST_USED_COOKIE = "nova_guest_used"
_GUEST_COOKIE_MAX_AGE = 365 * 86400


def _client_ip(request: Request) -> str:
    """取真实来源 IP：只信任已配置的反代，否则用直连地址。

    X-Forwarded-For 是客户端可以随便写的。默认直连部署下无条件采信它，
    等于把限流和「游客每网络一次」变成可绕过的摆设，所以先看来源是否在
    TRUSTED_PROXIES 里。
    """
    peer = request.client.host if request.client else None
    if settings.is_trusted_proxy(peer):
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()[:64]
        real_ip = (request.headers.get("x-real-ip") or "").strip()
        if real_ip:
            return real_ip[:64]
    return peer or "unknown"


def _cookie_secure(request: Request) -> bool:
    """HTTPS 下自动加 Secure，避免靠人记得改环境变量。

    COOKIE_SECURE 显式设置时以它为准；未设置时按本次请求的实际协议判断。
    uvicorn 只在来源可信时才把 X-Forwarded-Proto 写进 scheme，所以这里再
    按 TRUSTED_PROXIES 补一条兜底：反代没配 FORWARDED_ALLOW_IPS 时也能正确。
    """
    if settings.cookie_secure is not None:
        return settings.cookie_secure
    if request.url.scheme == "https":
        return True
    peer = request.client.host if request.client else None
    if settings.is_trusted_proxy(peer):
        proto = (request.headers.get("x-forwarded-proto") or "")
        if proto.split(",")[0].strip().lower() == "https":
            return True
    return False


def _prune(bucket: deque, now: float) -> None:
    while bucket and now - bucket[0] > _REG_WINDOW:
        bucket.popleft()


def _throttle(buckets: dict[str, deque], key: str, limit: int, message: str) -> None:
    """滑动窗口计数：记一次并检查上限。limit <= 0 表示关闭。

    注册用它：每来一次就占一格，「一小时内建了几个号」直接受限。
    """
    if limit <= 0:
        return
    now = time.time()
    bucket = buckets[key]
    _prune(bucket, now)
    if len(bucket) >= limit:
        raise HTTPException(status_code=429, detail=message)
    bucket.append(now)


def _check_registration_rate(request: Request) -> None:
    _throttle(
        _reg_buckets,
        _client_ip(request),
        settings.max_registrations_per_hour,
        "注册过于频繁，请稍后再试",
    )


# 桶按 key 无限增长（用户名由攻击者随意指定），超过这个量级就清一遍过期项。
_LOGIN_BUCKET_CAP = 20_000


def _login_bucket(buckets: dict[str, deque], key: str, now: float) -> deque:
    # 先建桶再清理：key 不能因为正好在清理里被删掉而丢失引用。
    buckets[key]
    if len(buckets) > _LOGIN_BUCKET_CAP:
        stale = [k for k, b in buckets.items() if not b or now - b[-1] > _REG_WINDOW]
        for stale_key in stale:
            del buckets[stale_key]
        if len(buckets) > _LOGIN_BUCKET_CAP:
            # 仍然过多（大量活跃 IP 刷随机用户名）：只保留最近活动的那些。
            keep = sorted(buckets.items(), key=lambda item: item[1][-1], reverse=True)
            buckets.clear()
            buckets.update(dict(keep[:_LOGIN_BUCKET_CAP]))
    return buckets[key]


def _login_keys(request: Request, username: str) -> tuple[str, str]:
    """两个维度：来源 IP，以及（IP, 账号）组合。

    只按 IP 挡不住针对同一账号的撞库；只按账号又会让任何人都能凭失败尝试
    把别人的账号锁住一小时（拿别人账号做拒绝服务）。组合维度两头兼顾，
    代价是分布式（多 IP）撞同一账号只能靠 IP 桶逐个拖慢。
    """
    ip = _client_ip(request)
    return ip, f"{ip}:{username.strip().lower()[:64]}"


def _record_login_failure(request: Request, username: str) -> None:
    """登录失败后把两个桶都推一格。

    _check_login_rate 只做判断不计数（否则一次成功登录也会消耗额度），
    真正记账发生在这里，所以「试了 N 次都没成功」才会被限。
    """
    now = time.time()
    ip_key, user_key = _login_keys(request, username)
    for buckets, key in (
        (_login_ip_buckets, ip_key),
        (_login_user_buckets, user_key),
    ):
        bucket = _login_bucket(buckets, key, now)
        _prune(bucket, now)
        bucket.append(now)


def _check_login_rate(request: Request, username: str) -> None:
    """登录限流：按来源 IP 和账号各算一次。

    只有失败才计数（见 login），正常登录不会消耗额度。账号维度跨 IP 累计，
    这样分布式撞库也会在打到同一账号时被拦住；代价是该账号会被临时锁住，
    但窗口只有 1 小时，且 MAX_LOGIN_ATTEMPTS_PER_HOUR 可调。
    """
    limit = settings.max_login_attempts_per_hour
    if limit <= 0:
        return
    ip_key, user_key = _login_keys(request, username)
    now = time.time()
    for buckets, key, message in (
        (_login_ip_buckets, ip_key, "登录尝试过于频繁，请稍后再试"),
        (_login_user_buckets, user_key, "该账号登录尝试过于频繁，请稍后再试"),
    ):
        bucket = _login_bucket(buckets, key, now)
        _prune(bucket, now)
        # 只看不记：记账由 _record_login_failure 负责，成功登录不消耗额度。
        if len(bucket) >= limit:
            raise HTTPException(status_code=429, detail=message)


def _set_cookie(response: Response, request: Request, user: dict) -> None:
    response.set_cookie(
        COOKIE_NAME,
        create_token(user),
        httponly=True,
        samesite="lax",
        secure=_cookie_secure(request),
        max_age=settings.token_ttl_days * 86400,
        path="/",
    )


def _ensure_server_mode() -> None:
    if settings.is_local:
        raise HTTPException(status_code=404, detail="本地模式不提供账号登录/注册")


@router.get("/auth/config", response_model=AuthConfigOut)
def auth_config():
    if settings.is_local:
        return AuthConfigOut(
            registration_mode="closed",
            guest_enabled=False,
            invite_required=False,
            min_password_length=settings.min_password_length,
            email_verification=False,
        )
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
    _ensure_server_mode()
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
async def login(body: LoginRequest, request: Request, response: Response):
    _ensure_server_mode()
    # 先看是否已经被刷爆，再验密码；否则撞库脚本可以无限重试。
    _check_login_rate(request, body.username)
    user = await authenticate(body.username, body.password)
    if not user:
        # 只有失败才计数：成功登录（含同一人反复刷新）不消耗额度。
        _record_login_failure(request, body.username)
        await log_audit(
            AuditAction.LOGIN_FAILED,
            details={"username": body.username},
            risk_level="warn",
        )
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    _set_cookie(response, request, user)
    await touch_login(user["id"])
    await log_audit(AuditAction.LOGIN, user_id=str(user["id"]), details={"username": user["username"]})
    return user


@router.post("/auth/register", response_model=RegisterOut)
async def register(body: RegisterRequest, request: Request, response: Response):
    _ensure_server_mode()
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

    _set_cookie(response, request, user)
    await log_audit("register", user_id=str(user["id"]), details={"username": user["username"]})
    return RegisterOut(user=user, recovery_code=recovery_code)


@router.post("/auth/guest", response_model=UserOut)
async def guest(request: Request, response: Response):
    _ensure_server_mode()
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
    _set_cookie(response, request, user)
    response.set_cookie(
        GUEST_USED_COOKIE,
        "1",
        httponly=True,
        samesite="lax",
        secure=_cookie_secure(request),
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
    _ensure_server_mode()
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/auth/me", response_model=UserOut)
async def me(user: dict = Depends(get_current_user)):
    return user


@router.patch("/auth/profile", response_model=UserOut)
async def update_my_profile(body: ProfileUpdateRequest, user: dict = Depends(get_current_user)):
    _ensure_server_mode()
    try:
        updated = await update_profile(user["id"], body.display_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return updated


@router.post("/auth/password", response_model=UserOut)
async def update_my_password(
    body: PasswordChangeRequest,
    request: Request,
    response: Response,
    user: dict = Depends(get_current_user),
):
    _ensure_server_mode()
    try:
        updated = await change_password(user["id"], body.current_password, body.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _set_cookie(response, request, updated)
    await log_audit("password_change", user_id=str(user["id"]), risk_level="warn")
    return updated


@router.post("/auth/password/reset", response_model=OkOut)
async def reset_password(body: PasswordResetRequest):
    _ensure_server_mode()
    try:
        await reset_password_with_recovery(body.username, body.recovery_code, body.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await log_audit("password_reset", details={"username": body.username}, risk_level="warn")
    return {"ok": True}


@router.post("/auth/password/reset/email", response_model=OkOut)
async def reset_password_by_email(body: EmailResetRequest):
    """用户名 + 邮箱验证码找回密码（邮箱须与账号绑定一致）。"""
    _ensure_server_mode()
    if not settings.email_enabled:
        raise HTTPException(status_code=503, detail="邮件服务未配置，请联系管理员")
    try:
        await reset_password_with_email_code(body.username, body.email, body.code, body.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await log_audit("password_reset_email", details={"username": body.username}, risk_level="warn")
    return {"ok": True}

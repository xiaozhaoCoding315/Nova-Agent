"""Authentication: bcrypt password hashing + JWT session cookie."""
import datetime

import bcrypt
import jwt
import structlog
from fastapi import Depends, HTTPException, Request

from app.config import settings
from app.db import execute, query

logger = structlog.get_logger()

COOKIE_NAME = "nova_token"

# Appended after the core user columns in every SELECT so the request-scoped
# user dict carries per-user quota overrides (NULL = inherit role tier).
QUOTA_SELECT = (
    ", quota_daily_tokens, quota_hourly_messages, quota_sandbox_daily, "
    "quota_job_hourly, quota_storage_mb, "
    "self_daily_tokens, self_hourly_messages, self_sandbox_daily"
)
QUOTA_KEYS = (
    "quota_daily_tokens", "quota_hourly_messages", "quota_sandbox_daily",
    "quota_job_hourly", "quota_storage_mb",
    "self_daily_tokens", "self_hourly_messages", "self_sandbox_daily",
)


def _with_quota(user: dict, row: tuple, offset: int) -> dict:
    for i, key in enumerate(QUOTA_KEYS):
        user[key] = row[offset + i] if len(row) > offset + i else None
    return user


def _active(user: dict) -> bool:
    if user.get("status", "active") != "active":
        return False
    expires_at = user.get("expires_at")
    if not expires_at:
        return True
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=datetime.timezone.utc)
    return expires_at > datetime.datetime.now(datetime.timezone.utc)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def create_token(user: dict) -> str:
    payload = {
        "sub": str(user["id"]),
        "username": user["username"],
        "role": user["role"],
        "ver": int(user.get("token_version", 0)),
        "exp": datetime.datetime.now(datetime.timezone.utc)
        + datetime.timedelta(days=settings.token_ttl_days),
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


async def get_user_by_username(username: str) -> dict | None:
    rows = await query(
        "SELECT id, username, password_hash, display_name, role, status, is_guest, "
        f"expires_at, token_version{QUOTA_SELECT} FROM users WHERE username = %s",
        (username,),
    )
    if not rows:
        return None
    r = rows[0]
    return _with_quota({
        "id": r[0], "username": r[1], "password_hash": r[2],
        "display_name": r[3] or r[1], "role": r[4], "status": r[5] or "active",
        "is_guest": bool(r[6]), "expires_at": r[7], "token_version": int(r[8] or 0),
    }, r, 9)


async def authenticate(username: str, password: str) -> dict | None:
    user = await get_user_by_username(username)
    if not user or not _active(user) or not verify_password(password, user["password_hash"]):
        return None
    return {
        "id": user["id"], "username": user["username"],
        "display_name": user["display_name"], "role": user["role"],
        "status": user["status"], "is_guest": user["is_guest"],
        "expires_at": user["expires_at"], "token_version": user["token_version"],
        "created_at": None,
    }


async def get_current_user(request: Request) -> dict:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[len("Bearer "):]
    if not token:
        raise HTTPException(status_code=401, detail="未登录")
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")

    rows = await query(
        "SELECT id, username, display_name, role, status, is_guest, expires_at, "
        f"token_version, created_at{QUOTA_SELECT} FROM users WHERE id = %s",
        (int(payload.get("sub", 0)),),
    )
    if not rows:
        raise HTTPException(status_code=401, detail="账号不存在")
    r = rows[0]
    user = _with_quota({
        "id": r[0], "username": r[1], "display_name": r[2] or r[1], "role": r[3],
        "status": r[4] or "active", "is_guest": bool(r[5]), "expires_at": r[6],
        "token_version": int(r[7] or 0), "created_at": r[8],
    }, r, 9)
    if not _active(user):
        raise HTTPException(status_code=401, detail="账号已禁用或体验已到期")
    if int(payload.get("ver", 0)) != user["token_version"]:
        raise HTTPException(status_code=401, detail="登录状态已失效，请重新登录")
    return user


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


async def ensure_default_users() -> str:
    """Idempotently seed admin + demo accounts. Env changes rotate the password."""
    seeded = []
    for role in ("admin", "demo"):
        username = settings.admin_username if role == "admin" else settings.demo_username
        password = settings.admin_password if role == "admin" else settings.demo_password
        if not password:
            password = "admin123" if role == "admin" else "demo123"
            logger.warning(
                "default_password_in_use",
                username=username,
                hint="set ADMIN_PASSWORD / DEMO_PASSWORD in .env before going public",
            )
        await execute(
            """
            INSERT INTO users (username, password_hash, display_name, role)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (username)
            DO UPDATE SET password_hash = EXCLUDED.password_hash, role = EXCLUDED.role
            """,
            (username, hash_password(password), username, role),
        )
        seeded.append(username)
    return "seeded: " + ",".join(seeded)
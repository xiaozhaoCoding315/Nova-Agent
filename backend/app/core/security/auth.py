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
        "exp": datetime.datetime.now(datetime.timezone.utc)
        + datetime.timedelta(days=settings.token_ttl_days),
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


async def get_user_by_username(username: str) -> dict | None:
    rows = await query(
        "SELECT id, username, password_hash, role FROM users WHERE username = %s",
        (username,),
    )
    if not rows:
        return None
    r = rows[0]
    return {"id": r[0], "username": r[1], "password_hash": r[2], "role": r[3]}


async def authenticate(username: str, password: str) -> dict | None:
    user = await get_user_by_username(username)
    if not user or not verify_password(password, user["password_hash"]):
        return None
    return {"id": user["id"], "username": user["username"], "role": user["role"]}


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
        "SELECT id, username, role FROM users WHERE id = %s",
        (int(payload.get("sub", 0)),),
    )
    if not rows:
        raise HTTPException(status_code=401, detail="账号不存在")
    r = rows[0]
    return {"id": r[0], "username": r[1], "role": r[2]}


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
            INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s)
            ON CONFLICT (username)
            DO UPDATE SET password_hash = EXCLUDED.password_hash, role = EXCLUDED.role
            """,
            (username, hash_password(password), role),
        )
        seeded.append(username)
    return "seeded: " + ",".join(seeded)
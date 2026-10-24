"""Account lifecycle: self-registration, guests, profile, password, admin ops."""
import re
import secrets
from datetime import datetime, timedelta, timezone

import psycopg

from app.config import settings
from app.core.security.auth import hash_password, verify_password
from app.db import execute, query

USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,32}$")
USER_COLUMNS = (
    "id, username, display_name, role, status, is_guest, expires_at, "
    "token_version, created_at"
)


def validate_username(username: str) -> str:
    value = (username or "").strip()
    if not USERNAME_RE.match(value):
        raise ValueError("用户名需为 3-32 位字母、数字或下划线")
    return value


def validate_password(password: str) -> str:
    value = password or ""
    if len(value) < settings.min_password_length:
        raise ValueError(f"密码至少需要 {settings.min_password_length} 位")
    if len(value) > 200:
        raise ValueError("密码过长")
    return value


def user_from_row(row: tuple) -> dict:
    return {
        "id": row[0],
        "username": row[1],
        "display_name": row[2] or row[1],
        "role": row[3],
        "status": row[4] or "active",
        "is_guest": bool(row[5]),
        "expires_at": row[6],
        "token_version": int(row[7] or 0),
        "created_at": row[8],
    }


def is_expired(user: dict) -> bool:
    expires_at = user.get("expires_at")
    if not expires_at:
        return False
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at <= datetime.now(timezone.utc)


def is_active(user: dict) -> bool:
    return user.get("status", "active") == "active" and not is_expired(user)


async def get_user_by_id(user_id: int) -> dict | None:
    rows = await query(
        f"SELECT {USER_COLUMNS} FROM users WHERE id = %s",
        (user_id,),
    )
    return user_from_row(rows[0]) if rows else None


async def get_user_by_username(username: str) -> dict | None:
    rows = await query(
        f"SELECT {USER_COLUMNS} FROM users WHERE username = %s",
        (username,),
    )
    return user_from_row(rows[0]) if rows else None


async def count_users() -> int:
    rows = await query("SELECT COUNT(*) FROM users")
    return int(rows[0][0]) if rows else 0


def generate_recovery_code() -> str:
    return secrets.token_hex(4).upper()


async def create_user(
    username: str,
    password: str,
    *,
    display_name: str = "",
    role: str = "demo",
    is_guest: bool = False,
    expires_at: datetime | None = None,
    recovery_code: str | None = None,
) -> dict:
    username = validate_username(username)
    validate_password(password)
    if role not in ("admin", "demo"):
        raise ValueError("无效的角色")
    if await count_users() >= settings.max_users:
        raise ValueError("账号数量已达当前部署上限，请联系管理员")

    display = (display_name or username).strip()[:80]
    recovery_hash = hash_password(recovery_code) if recovery_code else None
    try:
        rows = await execute(
            "INSERT INTO users "
            "(username, password_hash, display_name, role, is_guest, expires_at, recovery_code_hash) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) "
            f"RETURNING {USER_COLUMNS}",
            (
                username, hash_password(password), display, role,
                is_guest, expires_at, recovery_hash,
            ),
        )
    except psycopg.errors.UniqueViolation:
        raise ValueError("用户名已被占用")
    if not rows:
        raise RuntimeError("创建账号失败")
    return user_from_row(rows[0])


async def create_guest_user() -> tuple[dict, str]:
    username = f"guest_{secrets.token_hex(4)}"
    password = secrets.token_urlsafe(18)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.guest_ttl_hours)
    user = await create_user(
        username,
        password,
        display_name="游客",
        is_guest=True,
        expires_at=expires_at,
    )
    return user, password


async def touch_login(user_id: int) -> None:
    await execute("UPDATE users SET last_login_at = now() WHERE id = %s", (user_id,))


async def update_profile(user_id: int, display_name: str) -> dict:
    display = (display_name or "").strip()
    if not display:
        raise ValueError("显示名不能为空")
    if len(display) > 80:
        raise ValueError("显示名不能超过 80 个字符")
    rows = await execute(
        f"UPDATE users SET display_name = %s WHERE id = %s RETURNING {USER_COLUMNS}",
        (display, user_id),
    )
    if not rows:
        raise ValueError("账号不存在")
    return user_from_row(rows[0])


async def change_password(user_id: int, current_password: str, new_password: str) -> dict:
    rows = await query(
        "SELECT password_hash FROM users WHERE id = %s",
        (user_id,),
    )
    if not rows or not verify_password(current_password, rows[0][0]):
        raise ValueError("当前密码不正确")
    validate_password(new_password)
    await execute(
        "UPDATE users SET password_hash = %s, token_version = token_version + 1, "
        "password_updated_at = now() WHERE id = %s",
        (hash_password(new_password), user_id),
    )
    user = await get_user_by_id(user_id)
    if user is None:
        raise ValueError("账号不存在")
    return user


async def reset_password_with_recovery(username: str, recovery_code: str, new_password: str) -> None:
    rows = await query(
        "SELECT id, recovery_code_hash FROM users WHERE username = %s",
        (username.strip(),),
    )
    if not rows or not rows[0][1] or not verify_password(
        (recovery_code or "").strip(), rows[0][1]
    ):
        raise ValueError("用户名或恢复码不正确")
    validate_password(new_password)
    await execute(
        "UPDATE users SET password_hash = %s, token_version = token_version + 1, "
        "password_updated_at = now(), recovery_code_hash = NULL WHERE id = %s",
        (hash_password(new_password), rows[0][0]),
    )


async def list_users(limit: int = 200) -> list[dict]:
    rows = await query(
        f"SELECT {USER_COLUMNS} FROM users ORDER BY created_at DESC LIMIT %s",
        (limit,),
    )
    return [user_from_row(row) for row in rows]


async def admin_set_user_fields(
    user_id: int,
    *,
    status: str | None = None,
    role: str | None = None,
    display_name: str | None = None,
) -> dict:
    sets: list[str] = []
    params: list = []
    if status is not None:
        if status not in ("active", "disabled"):
            raise ValueError("无效的账号状态")
        sets.append("status = %s")
        params.append(status)
    if role is not None:
        if role not in ("admin", "demo"):
            raise ValueError("无效的角色")
        sets.append("role = %s")
        params.append(role)
    if display_name is not None:
        display = display_name.strip()
        if not display or len(display) > 80:
            raise ValueError("显示名需为 1-80 个字符")
        sets.append("display_name = %s")
        params.append(display)
    if not sets:
        raise ValueError("没有需要修改的字段")
    if status is not None or role is not None:
        sets.append("token_version = token_version + 1")
    params.append(user_id)
    rows = await execute(
        f"UPDATE users SET {', '.join(sets)} WHERE id = %s RETURNING {USER_COLUMNS}",
        tuple(params),
    )
    if not rows:
        raise ValueError("账号不存在")
    return user_from_row(rows[0])


async def admin_reset_password(user_id: int, new_password: str) -> None:
    validate_password(new_password)
    rows = await execute(
        "UPDATE users SET password_hash = %s, token_version = token_version + 1, "
        "password_updated_at = now() WHERE id = %s RETURNING id",
        (hash_password(new_password), user_id),
    )
    if not rows:
        raise ValueError("账号不存在")


async def assert_user_deletable(user_id: int) -> None:
    rows = await query("SELECT role, status FROM users WHERE id = %s", (user_id,))
    if not rows:
        raise ValueError("账号不存在")
    if rows[0][0] == "admin" and rows[0][1] == "active":
        admins = await query(
            "SELECT COUNT(*) FROM users WHERE role = 'admin' AND status = 'active' AND id <> %s",
            (user_id,),
        )
        if admins and int(admins[0][0]) == 0:
            raise ValueError("不能删除最后一个管理员")


async def admin_delete_user(user_id: int) -> None:
    await assert_user_deletable(user_id)
    await execute("DELETE FROM users WHERE id = %s", (user_id,))

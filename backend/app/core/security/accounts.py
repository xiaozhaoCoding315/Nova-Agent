"""Account lifecycle: self-registration, guests, profile, password, admin ops."""
import re
import secrets
from datetime import datetime, timedelta, timezone

import psycopg

from app.config import settings
from app.core.security.auth import hash_password, verify_password
from app.db import execute, query

USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,32}$")
# Per-user quota overrides set by admins (quota_*) and self-imposed budgets
# (self_*).  NULL = inherit the role-tier default; 0 = unlimited.
QUOTA_COLUMNS = (
    "quota_daily_tokens, quota_hourly_messages, quota_sandbox_daily, "
    "quota_job_hourly, quota_storage_mb, "
    "self_daily_tokens, self_hourly_messages, self_sandbox_daily"
)
USER_COLUMNS = (
    "id, username, display_name, role, status, is_guest, expires_at, "
    f"token_version, created_at, {QUOTA_COLUMNS}"
)


def validate_quota_value(value: int, field: str) -> int:
    value = int(value)
    if value < 0:
        raise ValueError(f"{field} 不能为负数（0 表示不限，留空表示跟随默认档）")
    if value > 2_000_000_000:
        raise ValueError(f"{field} 数值过大")
    return value


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
    user = {
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
    # Quota columns are appended after the core nine; tolerate shorter rows
    # from older callers/tests that only select the core columns.
    quota_keys = (
        "quota_daily_tokens", "quota_hourly_messages", "quota_sandbox_daily",
        "quota_job_hourly", "quota_storage_mb",
        "self_daily_tokens", "self_hourly_messages", "self_sandbox_daily",
    )
    for i, key in enumerate(quota_keys):
        user[key] = row[9 + i] if len(row) > 9 + i else None
    return user


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
    created_ip: str | None = None,
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
            "(username, password_hash, display_name, role, is_guest, expires_at, recovery_code_hash, created_ip) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
            f"RETURNING {USER_COLUMNS}",
            (
                username, hash_password(password), display, role,
                is_guest, expires_at, recovery_hash, (created_ip or "")[:64] or None,
            ),
        )
    except psycopg.errors.UniqueViolation:
        raise ValueError("用户名已被占用")
    if not rows:
        raise RuntimeError("创建账号失败")
    return user_from_row(rows[0])


async def create_guest_user(ip: str | None = None) -> tuple[dict, str]:
    username = f"guest_{secrets.token_hex(4)}"
    password = secrets.token_urlsafe(18)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.guest_ttl_hours)
    user = await create_user(
        username,
        password,
        display_name="游客",
        is_guest=True,
        expires_at=expires_at,
        created_ip=ip,
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


async def list_users_with_usage(limit: int = 200) -> list[dict]:
    rows = await query(
        f"""
        SELECT u.id, u.username, u.display_name, u.role, u.status, u.is_guest,
               u.expires_at, u.token_version, u.created_at, {QUOTA_COLUMNS},
               u.last_login_at,
               (SELECT COUNT(*) FROM sessions s WHERE s.user_id = u.id),
               (SELECT COUNT(*) FROM repos r WHERE r.user_id = u.id),
               (SELECT COUNT(*) FROM user_files f WHERE f.user_id = u.id),
               (SELECT COALESCE(SUM(f.size), 0) FROM user_files f WHERE f.user_id = u.id),
               (SELECT COALESCE(SUM(l.prompt_tokens + l.completion_tokens), 0)
                FROM usage_log l WHERE l.user_id = u.id)
        FROM users u
        ORDER BY u.created_at DESC
        LIMIT %s
        """,
        (limit,),
    )
    result = []
    for row in rows:
        user = user_from_row(row[:9] + tuple(row[9:17]))
        user.update({
            "last_login_at": row[17],
            "sessions": int(row[18] or 0),
            "repos": int(row[19] or 0),
            "files": int(row[20] or 0),
            "storage_bytes": int(row[21] or 0),
            "tokens_total": int(row[22] or 0),
        })
        result.append(user)
    return result


async def admin_set_user_fields(
    user_id: int,
    *,
    status: str | None = None,
    role: str | None = None,
    display_name: str | None = None,
    quotas: dict[str, int | None] | None = None,
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
    for field, value in (quotas or {}).items():
        if value is not None:
            value = validate_quota_value(value, field)
        sets.append(f"{field} = %s")
        params.append(value)
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


SELF_QUOTA_FIELDS = ("self_daily_tokens", "self_hourly_messages", "self_sandbox_daily")


async def set_self_quota(user_id: int, values: dict[str, int | None]) -> dict:
    """Update the user's own budget caps. Self caps only tighten, never raise,
    the effective limit (enforced at resolution time in limits.py)."""
    sets: list[str] = []
    params: list = []
    for field in SELF_QUOTA_FIELDS:
        if field not in values:
            continue
        value = values[field]
        if value is not None:
            value = validate_quota_value(value, field)
        sets.append(f"{field} = %s")
        params.append(value)
    if not sets:
        raise ValueError("没有需要修改的额度字段")
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


# ---------------------------------------------------------------------------
# 邀请码（动态注册凭证，管理员在设置页生成/管理）
# ---------------------------------------------------------------------------

INVITE_COLUMNS = "id, code, note, max_uses, used_count, created_by, created_at, expires_at"
_INVITE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # 去掉易混淆的 I/L/O/0/1


def generate_invite_code() -> str:
    body = "-".join(
        "".join(secrets.choice(_INVITE_ALPHABET) for _ in range(4)) for _ in range(3)
    )
    return f"NOVA-{body}"


def _invite_from_row(row: tuple) -> dict:
    return {
        "id": int(row[0]),
        "code": row[1],
        "note": row[2] or "",
        "max_uses": int(row[3]),
        "used_count": int(row[4]),
        "created_by": row[5],
        "created_at": row[6],
        "expires_at": row[7],
    }


async def create_invite(
    *, note: str = "", max_uses: int = 1, expires_days: int | None = None, created_by: int
) -> dict:
    max_uses = int(max_uses)
    if not 1 <= max_uses <= 10_000:
        raise ValueError("可用次数需在 1-10000 之间")
    expires_at = None
    if expires_days and int(expires_days) > 0:
        expires_at = datetime.now(timezone.utc) + timedelta(days=int(expires_days))
    for _ in range(5):  # 撞唯一键时重换码
        code = generate_invite_code()
        try:
            rows = await execute(
                "INSERT INTO invite_codes (code, note, max_uses, created_by, expires_at) "
                "VALUES (%s, %s, %s, %s, %s) "
                f"RETURNING {INVITE_COLUMNS}",
                (code, (note or "").strip()[:120] or None, max_uses, created_by, expires_at),
            )
            break
        except psycopg.errors.UniqueViolation:
            continue
    else:
        raise RuntimeError("邀请码生成失败，请重试")
    return _invite_from_row(rows[0])


async def list_invites() -> list[dict]:
    rows = await query(
        f"SELECT {INVITE_COLUMNS} FROM invite_codes ORDER BY created_at DESC LIMIT 200"
    )
    return [_invite_from_row(row) for row in rows]


async def delete_invite(invite_id: int) -> bool:
    rows = await execute(
        "DELETE FROM invite_codes WHERE id = %s RETURNING id", (int(invite_id),)
    )
    return bool(rows)


async def consume_invite(code: str) -> dict:
    """原子核销：有效且未超次数/未过期才计数，否则抛 ValueError。"""
    value = (code or "").strip().upper()
    rows = await execute(
        "UPDATE invite_codes SET used_count = used_count + 1 "
        "WHERE code = %s AND used_count < max_uses "
        "AND (expires_at IS NULL OR expires_at > now()) "
        f"RETURNING {INVITE_COLUMNS}",
        (value,),
    )
    if not rows:
        raise ValueError("邀请码无效、已用完或已过期")
    return _invite_from_row(rows[0])


async def register_with_invite(
    username: str,
    password: str,
    *,
    display_name: str = "",
    invite_code: str,
    recovery_code: str,
    created_ip: str | None = None,
) -> dict:
    """先建号再核销邀请码；核销失败则回删账号，保证邀请码不被无效占用。"""
    user = await create_user(
        username,
        password,
        display_name=display_name,
        role="demo",
        recovery_code=recovery_code,
        created_ip=created_ip,
    )
    try:
        await consume_invite(invite_code)
    except ValueError:
        await execute("DELETE FROM users WHERE id = %s", (user["id"],))
        raise
    return user


# ---------------------------------------------------------------------------
# 邮箱验证码（注册验证 / 找回密码）
# ---------------------------------------------------------------------------

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
_EMAIL_CODE_TTL_S = 60  # 同一邮箱两次发码的最小间隔


def validate_email(email: str | None) -> str:
    value = (email or "").strip().lower()
    if not value or not EMAIL_RE.match(value) or len(value) > 190:
        raise ValueError("请输入有效的邮箱地址")
    return value


async def request_email_code(email: str, purpose: str) -> str:
    """生成并存储验证码（哈希存储），返回明文码给调用方发送。"""
    from app.core.security.auth import hash_password
    from app.core.security.mailer import generate_email_code

    email = validate_email(email)
    if purpose not in ("register", "reset"):
        raise ValueError("不支持的验证码用途")
    recent = await query(
        "SELECT created_at FROM email_codes WHERE email = %s AND purpose = %s "
        "ORDER BY created_at DESC LIMIT 1",
        (email, purpose),
    )
    if recent:
        from datetime import datetime, timezone
        created = recent[0][0]
        if created and (datetime.now(timezone.utc) - created).total_seconds() < _EMAIL_CODE_TTL_S:
            raise ValueError("发送太频繁，请 1 分钟后再试")
    hour_count = await query(
        "SELECT COUNT(*) FROM email_codes WHERE email = %s "
        "AND created_at > now() - interval '1 hour'",
        (email,),
    )
    if hour_count and int(hour_count[0][0]) >= 5:
        raise ValueError("该邮箱验证码请求过多，请稍后再试")

    code = generate_email_code()
    await execute(
        "INSERT INTO email_codes (email, code_hash, purpose, expires_at) "
        "VALUES (%s, %s, %s, now() + (%s * interval '1 minute'))",
        (email, hash_password(code), purpose, settings.email_code_ttl_minutes),
    )
    return code


async def verify_email_code(email: str, code: str, purpose: str, *, consume: bool = True) -> None:
    from app.core.security.auth import verify_password

    email = validate_email(email)
    rows = await query(
        "SELECT id, code_hash FROM email_codes WHERE email = %s AND purpose = %s "
        "AND used_at IS NULL AND expires_at > now() ORDER BY created_at DESC LIMIT 1",
        (email, purpose),
    )
    if not rows:
        raise ValueError("验证码不存在或已过期，请重新获取")
    if not verify_password((code or "").strip(), rows[0][1]):
        raise ValueError("验证码不正确")
    if consume:
        await execute("UPDATE email_codes SET used_at = now() WHERE id = %s", (rows[0][0],))


async def email_taken(email: str) -> bool:
    rows = await query("SELECT 1 FROM users WHERE email = %s LIMIT 1", (email,))
    return bool(rows)


async def bind_email_after_register(user: dict, email: str, email_code: str) -> None:
    """建号后绑定并核销邮箱验证码；任一步失败回删账号，保证一致性。"""
    email = validate_email(email)
    if await email_taken(email):
        await execute("DELETE FROM users WHERE id = %s", (user["id"],))
        raise ValueError("该邮箱已被注册")
    try:
        await verify_email_code(email, email_code, "register", consume=True)
    except ValueError:
        await execute("DELETE FROM users WHERE id = %s", (user["id"],))
        raise
    await execute(
        "UPDATE users SET email = %s, email_verified = TRUE WHERE id = %s",
        (email, user["id"]),
    )


async def reset_password_with_email_code(username: str, email: str, code: str, new_password: str) -> None:
    """用户名 + 邮箱验证码找回密码（邮箱必须与该账号绑定的一致）。"""
    username = validate_username(username)
    email = validate_email(email)
    rows = await query(
        "SELECT id, email, email_verified FROM users WHERE username = %s", (username,)
    )
    if not rows or not rows[0][2] or (rows[0][1] or "").lower() != email:
        raise ValueError("账号不存在，或该账号未绑定此邮箱")
    await verify_email_code(email, code, "reset", consume=True)

    if len(new_password or "") < settings.min_password_length:
        raise ValueError(f"密码至少需要 {settings.min_password_length} 位")
    await execute(
        "UPDATE users SET password_hash = %s, password_updated_at = now(), "
        "token_version = token_version + 1 WHERE id = %s",
        (hash_password(new_password), rows[0][0]),
    )

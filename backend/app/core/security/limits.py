"""Per-user rate limiting (in-process sliding window) and daily budgets (PG aggregates)."""
import time
from collections import defaultdict, deque

import structlog
from fastapi import HTTPException

from app.config import settings
from app.db import query

logger = structlog.get_logger()

_WINDOW_S = 3600
_buckets: dict[str, deque] = defaultdict(deque)


def _rate_check(user: dict, kind: str, limit: int) -> None:
    key = f"{user['id']}:{kind}"
    now = time.time()
    bucket = _buckets[key]
    while bucket and now - bucket[0] > _WINDOW_S:
        bucket.popleft()
    if len(bucket) >= limit:
        raise HTTPException(
            status_code=429,
            detail=f"请求过于频繁（每小时上限 {limit} 次），请稍后再试",
        )
    bucket.append(now)


def messages_last_hour(user_id: int) -> int:
    bucket = _buckets.get(f"{user_id}:chat")
    if not bucket:
        return 0
    now = time.time()
    while bucket and now - bucket[0] > _WINDOW_S:
        bucket.popleft()
    return len(bucket)


def _resolve(user: dict, override_key: str, self_key: str | None, role_value: int) -> int:
    """Effective limit = admin override (or role tier) capped by the user's
    self-imposed budget.  Convention: 0 = unlimited, NULL = inherit tier.
    A self budget of 0/NULL means "no self restriction"."""
    value = user.get(override_key)
    value = int(role_value) if value is None else int(value)
    if self_key:
        self_value = user.get(self_key)
        if self_value is not None and int(self_value) > 0:
            value = int(self_value) if value <= 0 else min(value, int(self_value))
    return value


def hourly_message_limit(user: dict) -> int:
    if user.get("is_guest"):
        tier = settings.guest_hourly_messages
    else:
        tier = settings.admin_hourly_messages if user["role"] == "admin" else settings.demo_hourly_messages
    return _resolve(user, "quota_hourly_messages", "self_hourly_messages", tier)


def daily_token_budget(user: dict) -> int:
    if user.get("is_guest"):
        tier = settings.guest_daily_tokens
    else:
        tier = settings.admin_daily_tokens if user["role"] == "admin" else settings.demo_daily_tokens
    return _resolve(user, "quota_daily_tokens", "self_daily_tokens", tier)


def sandbox_daily_limit(user: dict) -> int:
    if user.get("is_guest"):
        tier = settings.guest_sandbox_daily
    else:
        tier = settings.admin_sandbox_daily if user["role"] == "admin" else settings.demo_sandbox_daily
    return _resolve(user, "quota_sandbox_daily", "self_sandbox_daily", tier)


async def tokens_used_today(user_id: int) -> int:
    rows = await query(
        "SELECT COALESCE(SUM(prompt_tokens + completion_tokens), 0) FROM usage_log "
        "WHERE user_id = %s AND created_at >= date_trunc('day', now())",
        (user_id,),
    )
    return int(rows[0][0]) if rows else 0


async def sandbox_runs_today(user_id: int) -> int:
    rows = await query(
        "SELECT COUNT(*) FROM audit_log WHERE user_id = %s AND action = 'sandbox_run' "
        "AND created_at >= date_trunc('day', now())",
        (str(user_id),),
    )
    return int(rows[0][0]) if rows else 0


async def check_chat_quota(user: dict) -> None:
    """Raise 429 when the hourly rate or the daily token budget is exhausted."""
    limit = hourly_message_limit(user)
    if limit > 0:
        _rate_check(user, "chat", limit)
    budget = daily_token_budget(user)
    if budget > 0:
        used = await tokens_used_today(user["id"])
        if used >= budget:
            raise HTTPException(
                status_code=429,
                detail=f"今日 token 配额已用完（{budget}），明天再试",
            )


async def check_sandbox_quota(user: dict) -> None:
    limit = sandbox_daily_limit(user)
    if limit > 0:
        used = await sandbox_runs_today(user["id"])
        if used >= limit:
            raise HTTPException(
                status_code=429,
                detail=f"今日代码执行次数已用完（上限 {limit} 次）",
            )


def job_hourly_limit(user: dict) -> int:
    if user.get("is_guest"):
        tier = settings.guest_job_hourly
    else:
        tier = settings.admin_job_hourly if user["role"] == "admin" else settings.demo_job_hourly
    return _resolve(user, "quota_job_hourly", None, tier)


def check_job_quota(user: dict, kind: str) -> None:
    """Rate-limit expensive background entrypoints (import/reindex/task/builder)."""
    limit = job_hourly_limit(user)
    if limit > 0:
        _rate_check(user, f"job:{kind}", limit)


def check_search_quota(user: dict) -> None:
    """Search hits the embedding API; allow more than chat but still bound it."""
    limit = hourly_message_limit(user) * 10
    if limit > 0:
        _rate_check(user, "search", limit)


async def ensure_token_budget(
    user: dict | None = None,
    *,
    user_id: int | None = None,
    extra_tokens: int = 0,
) -> None:
    """Raise 429 when today's token budget is exhausted.

    ``extra_tokens`` accounts for usage accumulated inside the current turn,
    which is not yet visible in ``usage_log``.
    """
    if user is None:
        if user_id is None:
            return
        rows = await query(
            "SELECT id, role, is_guest, quota_daily_tokens, self_daily_tokens "
            "FROM users WHERE id = %s",
            (user_id,),
        )
        if not rows:
            return
        user = {
            "id": rows[0][0], "role": rows[0][1], "is_guest": bool(rows[0][2]),
            "quota_daily_tokens": rows[0][3], "self_daily_tokens": rows[0][4],
        }

    budget = daily_token_budget(user)
    if budget <= 0:
        return
    used = await tokens_used_today(user["id"])
    if used + max(int(extra_tokens or 0), 0) >= budget:
        raise HTTPException(
            status_code=429,
            detail=f"今日 token 配额已用完（{budget}），请明天再试或联系管理员",
        )
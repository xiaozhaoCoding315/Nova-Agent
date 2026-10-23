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


def hourly_message_limit(user: dict) -> int:
    return settings.admin_hourly_messages if user["role"] == "admin" else settings.demo_hourly_messages


def daily_token_budget(user: dict) -> int:
    return settings.admin_daily_tokens if user["role"] == "admin" else settings.demo_daily_tokens


def sandbox_daily_limit(user: dict) -> int:
    return settings.admin_sandbox_daily if user["role"] == "admin" else settings.demo_sandbox_daily


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
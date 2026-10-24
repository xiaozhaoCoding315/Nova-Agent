"""Self-service quota budgets: users view usage and tighten their own limits."""
import asyncio

from fastapi import APIRouter, Depends, HTTPException

from app.core.security.accounts import set_self_quota
from app.core.security.audit import log_audit
from app.core.security.auth import get_current_user
from app.core.security.limits import (
    daily_token_budget,
    hourly_message_limit,
    job_hourly_limit,
    messages_last_hour,
    sandbox_daily_limit,
    sandbox_runs_today,
    tokens_used_today,
)
from app.core.storage.user_storage import storage_limit_bytes
from app.models.schemas import SelfQuotaOut, SelfQuotaUpdateRequest

router = APIRouter()


def _quota_payload(user: dict, today_tokens: int, sb_runs: int) -> SelfQuotaOut:
    budget = daily_token_budget(user)
    return SelfQuotaOut(
        self_daily_tokens=user.get("self_daily_tokens"),
        self_hourly_messages=user.get("self_hourly_messages"),
        self_sandbox_daily=user.get("self_sandbox_daily"),
        today_tokens=today_tokens,
        daily_token_budget=budget,
        tokens_remaining=None if budget <= 0 else max(budget - today_tokens, 0),
        messages_last_hour=messages_last_hour(user["id"]),
        hourly_message_limit=hourly_message_limit(user),
        sandbox_runs_today=sb_runs,
        sandbox_daily_limit=sandbox_daily_limit(user),
        job_hourly_limit=job_hourly_limit(user),
        storage_limit_mb=storage_limit_bytes(user) // (1024 * 1024),
    )


@router.get("/settings/quota", response_model=SelfQuotaOut)
async def get_quota(user: dict = Depends(get_current_user)):
    today_tokens, sb_runs = await asyncio.gather(
        tokens_used_today(user["id"]),
        sandbox_runs_today(user["id"]),
    )
    return _quota_payload(user, today_tokens, sb_runs)


@router.put("/settings/quota", response_model=SelfQuotaOut)
async def update_quota(
    body: SelfQuotaUpdateRequest,
    user: dict = Depends(get_current_user),
):
    sent = body.model_fields_set
    values = {
        key: getattr(body, key)
        for key in ("self_daily_tokens", "self_hourly_messages", "self_sandbox_daily")
        if key in sent
    }
    if not values:
        raise HTTPException(status_code=400, detail="没有需要修改的额度字段")
    try:
        updated = await set_self_quota(user["id"], values)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await log_audit("self_quota_update", user_id=str(user["id"]),
                    details={f"self:{k}": v for k, v in values.items()})
    today_tokens, sb_runs = await asyncio.gather(
        tokens_used_today(user["id"]),
        sandbox_runs_today(user["id"]),
    )
    return _quota_payload(updated, today_tokens, sb_runs)

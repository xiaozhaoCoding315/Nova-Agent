"""Status endpoints: real health probes + usage/quota reporting."""
import asyncio
import time

from fastapi import APIRouter, Depends

from app.config import settings
from app.core.security.auth import get_current_user
from app.core.security.limits import (
    daily_token_budget,
    hourly_message_limit,
    messages_last_hour,
    sandbox_daily_limit,
    sandbox_runs_today,
    tokens_used_today,
)
from app.models.schemas import HealthOut, UsageOut

router = APIRouter()

VERSION = "2.0.0"
_STARTED_AT = time.time()

CHECK_TIMEOUT = 5


async def _check_postgres() -> str:
    try:
        from app.db import query
        await asyncio.wait_for(query("SELECT 1"), timeout=CHECK_TIMEOUT)
        return "ok"
    except Exception as exc:  # noqa: BLE001
        return f"failed: {exc}"


async def _check_qdrant() -> str:
    try:
        from app.db.qdrant import count_points
        await asyncio.wait_for(count_points(), timeout=CHECK_TIMEOUT)
        return "ok"
    except Exception as exc:  # noqa: BLE001
        return f"failed: {exc}"


def _check_llm() -> str:
    if not settings.llm_configured:
        return "failed: no API key configured"
    return f"ok: {','.join(settings.llm_priority_list)}"


def _check_embedding() -> str:
    if not settings.dashscope_api_key:
        return "failed: DASHSCOPE_API_KEY missing (dense retrieval degrades to keyword-only)"
    return f"ok: {settings.embedding_model}"


async def _check_sandbox() -> dict:
    if not settings.sandbox_enabled:
        return {"available": False, "reason": "disabled by config"}

    from app.core.sandbox.runtime import is_docker_available

    try:
        docker_ok = await asyncio.wait_for(asyncio.to_thread(is_docker_available), timeout=CHECK_TIMEOUT)
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "reason": f"docker check failed: {exc}"}
    if not docker_ok:
        return {"available": False, "reason": "docker daemon not reachable"}

    def _image_exists() -> bool:
        import subprocess
        result = subprocess.run(
            ["docker", "image", "inspect", settings.sandbox_image],
            capture_output=True,
            timeout=CHECK_TIMEOUT,
        )
        return result.returncode == 0

    try:
        has_image = await asyncio.wait_for(asyncio.to_thread(_image_exists), timeout=CHECK_TIMEOUT + 2)
    except Exception:  # noqa: BLE001
        has_image = False
    return {
        "available": has_image,
        "image": settings.sandbox_image,
        "reason": "ok" if has_image else "sandbox image not built (docker build -f Dockerfile.sandbox -t nova-sandbox:latest .)",
    }


@router.get("/status/health", response_model=HealthOut)
async def health():
    postgres, qdrant = await asyncio.gather(_check_postgres(), _check_qdrant())
    sandbox = await _check_sandbox()
    components = {
        "postgres": postgres,
        "qdrant": qdrant,
        "llm": _check_llm(),
        "embedding": _check_embedding(),
        "sandbox": sandbox,
        "uptime_s": int(time.time() - _STARTED_AT),
        "env": settings.app_env,
    }
    core_ok = postgres == "ok" and qdrant == "ok" and settings.llm_configured
    return HealthOut(status="ok" if core_ok else "degraded", version=VERSION, components=components)


@router.get("/status/usage", response_model=UsageOut)
async def usage(user: dict = Depends(get_current_user)):
    used, sb_runs = await asyncio.gather(
        tokens_used_today(user["id"]),
        sandbox_runs_today(user["id"]),
    )
    budget = daily_token_budget(user)
    return UsageOut(
        today_tokens=used,
        daily_token_budget=budget,
        tokens_remaining=None if budget <= 0 else max(budget - used, 0),
        messages_last_hour=messages_last_hour(user["id"]),
        hourly_message_limit=hourly_message_limit(user),
        sandbox_runs_today=sb_runs,
        sandbox_daily_limit=sandbox_daily_limit(user),
    )
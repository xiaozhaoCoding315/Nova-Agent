"""Per-user model credentials: view, save, delete and connection test."""
import asyncio
import time

from fastapi import APIRouter, Depends, HTTPException

from app.config import settings
from app.core.llm.factory import OpenAICompatibleLLM, server_default_model
from app.core.llm.user_settings import (
    delete_user_config,
    get_user_config,
    provider_by_id,
    provider_presets,
    save_user_config,
)
from app.core.security.auth import get_current_user
from app.core.security.redaction import redact_text
from app.models.schemas import LlmSettingsOut, LlmSettingsUpdate, LlmTestOut

router = APIRouter()


def _public_view(config: dict | None, user: dict) -> LlmSettingsOut:
    has_key = bool(config and config.get("api_key"))
    # 服务端共享 Key 的适用范围随账号而变：游客/管理员可用，注册用户需自带 Key。
    server_applies = bool(
        settings.llm_allow_server_fallback
        and (
            user.get("is_guest")
            or user.get("role") == "admin"
            or settings.llm_server_fallback_registered
        )
    )
    if has_key:
        source = "user"
    elif settings.llm_configured and server_applies:
        source = "server"
    else:
        source = "none"

    return LlmSettingsOut(
        source=source,
        configured=has_key,
        provider=config["provider"] if config else None,
        model=config["model"] if has_key else server_default_model(),
        base_url=config["base_url"] if has_key else None,
        has_key=has_key,
        key_hint=config.get("key_hint") if has_key else None,
        server_model=server_default_model(),
        allow_server_fallback=server_applies,
        context_window=config.get("context_window") if config else None,
        reasoning_effort=config.get("reasoning_effort") if config else None,
        providers=provider_presets(),
        updated_at=config.get("updated_at") if config else None,
    )


@router.get("/settings/llm", response_model=LlmSettingsOut)
async def get_llm_settings(user: dict = Depends(get_current_user)):
    return _public_view(await get_user_config(user["id"]), user)


@router.put("/settings/llm", response_model=LlmSettingsOut)
async def update_llm_settings(
    body: LlmSettingsUpdate,
    user: dict = Depends(get_current_user),
):
    try:
        await save_user_config(
            user["id"],
            provider=body.provider,
            model=body.model,
            base_url=body.base_url,
            api_key=body.api_key,
            context_window=body.context_window,
            reasoning_effort=body.reasoning_effort,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _public_view(await get_user_config(user["id"]), user)


@router.delete("/settings/llm", response_model=LlmSettingsOut)
async def clear_llm_settings(user: dict = Depends(get_current_user)):
    await delete_user_config(user["id"])
    return _public_view(None, user)


@router.post("/settings/llm/test", response_model=LlmTestOut)
async def test_llm_settings(
    body: LlmSettingsUpdate,
    user: dict = Depends(get_current_user),
):
    existing = await get_user_config(user["id"])
    api_key = (body.api_key or "").strip() or (existing["api_key"] if existing else "")
    if not api_key:
        raise HTTPException(status_code=400, detail="请先填写 API Key")

    preset = provider_by_id(body.provider)
    if not preset:
        raise HTTPException(status_code=400, detail="不支持的模型服务商")
    base_url = (body.base_url or preset.get("base_url") or "").strip()
    model = body.model.strip()

    started = time.perf_counter()
    try:
        llm = OpenAICompatibleLLM(api_key, base_url, model)
        async with asyncio.timeout(20):
            async for _ in llm.astream(
                [{"role": "user", "content": "Reply with OK only."}],
                max_tokens=8,
            ):
                break
        elapsed = int((time.perf_counter() - started) * 1000)
        return LlmTestOut(ok=True, model=model, latency_ms=elapsed, message="连接成功，已收到模型响应")
    except TimeoutError:
        elapsed = int((time.perf_counter() - started) * 1000)
        return LlmTestOut(
            ok=False, model=model, latency_ms=elapsed,
            message="连接超时：部分思考模型首 token 较慢，可先保存后在对话中验证",
        )
    except Exception as exc:  # noqa: BLE001
        elapsed = int((time.perf_counter() - started) * 1000)
        return LlmTestOut(
            ok=False, model=model, latency_ms=elapsed,
            message=redact_text(str(exc))[:300],
        )

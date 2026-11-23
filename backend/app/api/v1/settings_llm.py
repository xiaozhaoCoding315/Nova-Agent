"""Per-user model credentials: catalog, CRUD, default and connection test."""
import asyncio
import time

from fastapi import APIRouter, Depends, HTTPException

from app.config import settings
from app.core.llm.anthropic import AnthropicLLM
from app.core.llm.factory import OpenAICompatibleLLM, server_default_model
from app.core.llm.providers import get_provider, provider_list, resolve_base_url
from app.core.llm.user_settings import (
    delete_user_config,
    get_user_config,
    list_user_configs,
    save_user_config,
    set_default_provider,
)
from app.core.security.auth import get_current_user
from app.core.security.redaction import redact_text
from app.models.schemas import (
    LlmCredentialOut,
    LlmCredentialUpdate,
    LlmProviderOut,
    LlmSettingsOut,
    LlmSettingsUpdate,
    LlmTestOut,
    OkOut,
)

router = APIRouter()

KEYLESS_PROVIDERS = {"ollama"}


def _credential_view(config: dict) -> LlmCredentialOut:
    spec = get_provider(config["provider"])
    return LlmCredentialOut(
        provider=config["provider"],
        label=spec.label if spec else config["provider"],
        icon=spec.icon if spec else "custom",
        model=config["model"],
        base_url=config["base_url"],
        has_key=bool(config.get("api_key")),
        key_hint=config.get("key_hint") or None,
        context_window=config.get("context_window"),
        reasoning_effort=config.get("reasoning_effort"),
        is_default=bool(config.get("is_default")),
        updated_at=config.get("updated_at"),
    )


def _public_view(
    config: dict | None, user: dict, configs: list[dict] | None = None,
) -> LlmSettingsOut:
    # Keyless local providers (Ollama) are usable without an API key. ``has_key``
    # stays key-based because the credential editor uses it to mask the field.
    has_key = bool(config and config.get("api_key"))
    usable = bool(config) and (
        bool(config.get("api_key")) or config.get("provider") in KEYLESS_PROVIDERS
    )
    # With BYOK closed the shared key must serve every account: a registered
    # user has no credential of their own to fall back on.
    byok_enabled = settings.llm_byok_open
    server_applies = bool(
        settings.llm_allow_server_fallback
        and (
            not byok_enabled
            or user.get("is_guest")
            or user.get("role") == "admin"
            or settings.llm_server_fallback_registered
        )
    )
    # Stored credentials are only reported when this surface may use them;
    # otherwise the picker would offer models the server ignores.
    active = config if (usable and byok_enabled) else None
    if active is not None:
        source = "user"
    elif settings.llm_configured and server_applies:
        source = "server"
    else:
        source = "none"

    providers = provider_list() if byok_enabled else []
    credentials = [
        _credential_view(item) for item in (configs or [])
    ] if byok_enabled else []

    return LlmSettingsOut(
        source=source,
        configured=active is not None,
        provider=active["provider"] if active else None,
        model=active["model"] if active else server_default_model(),
        base_url=active["base_url"] if active else None,
        has_key=has_key and byok_enabled,
        key_hint=active.get("key_hint") if has_key and active else None,
        server_model=server_default_model(),
        allow_server_fallback=server_applies and settings.llm_configured,
        byok_enabled=byok_enabled,
        context_window=active.get("context_window") if active else None,
        reasoning_effort=active.get("reasoning_effort") if active else None,
        providers=providers,
        credentials=credentials,
        updated_at=active.get("updated_at") if active else None,
    )


async def _public_for(user: dict) -> LlmSettingsOut:
    if not settings.llm_byok_open:
        return _public_view(None, user, [])
    configs = await list_user_configs(user["id"])
    default = next((item for item in configs if item.get("is_default")), None)
    if default is None and configs:
        default = configs[0]
    return _public_view(default, user, configs)


def _require_byok() -> None:
    """Refuse credential writes on a surface that has none.

    The web UI hides the editor when ``byok_enabled`` is false, but the
    endpoint must not depend on the UI for that: a saved credential here
    would be silently ignored by the factory.
    """
    if not settings.llm_byok_open:
        raise HTTPException(
            status_code=403,
            detail="本服务使用统一模型，不支持自定义 API Key；需要自定义模型请下载桌面客户端",
        )


@router.get("/settings/llm/providers", response_model=list[LlmProviderOut])
async def list_providers(user: dict = Depends(get_current_user)):
    return provider_list()


@router.get("/settings/llm/credentials", response_model=list[LlmCredentialOut])
async def list_credentials(user: dict = Depends(get_current_user)):
    if not settings.llm_byok_open:
        return []
    return [_credential_view(item) for item in await list_user_configs(user["id"])]


@router.put(
    "/settings/llm/credentials/{provider}", response_model=LlmCredentialOut,
)
async def save_credential(
    provider: str,
    body: LlmCredentialUpdate,
    user: dict = Depends(get_current_user),
):
    _require_byok()
    try:
        config = await save_user_config(
            user["id"],
            provider=provider,
            model=body.model,
            base_url=body.base_url,
            api_key=body.api_key,
            context_window=body.context_window,
            reasoning_effort=body.reasoning_effort,
            is_default=body.is_default,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _credential_view(config)


@router.delete(
    "/settings/llm/credentials/{provider}", response_model=OkOut,
)
async def delete_credential(provider: str, user: dict = Depends(get_current_user)):
    _require_byok()
    if not await delete_user_config(user["id"], provider):
        raise HTTPException(status_code=404, detail="该厂商尚未配置")
    return {"ok": True}


@router.post(
    "/settings/llm/credentials/{provider}/default",
    response_model=LlmCredentialOut,
)
async def make_default(provider: str, user: dict = Depends(get_current_user)):
    _require_byok()
    config = await set_default_provider(user["id"], provider)
    if config is None:
        raise HTTPException(status_code=404, detail="该厂商尚未配置")
    return _credential_view(config)


@router.get("/settings/llm", response_model=LlmSettingsOut)
async def get_llm_settings(user: dict = Depends(get_current_user)):
    return await _public_for(user)


@router.put("/settings/llm", response_model=LlmSettingsOut)
async def update_llm_settings(
    body: LlmSettingsUpdate,
    user: dict = Depends(get_current_user),
):
    _require_byok()
    try:
        await save_user_config(
            user["id"],
            provider=body.provider,
            model=body.model,
            base_url=body.base_url,
            api_key=body.api_key,
            context_window=body.context_window,
            reasoning_effort=body.reasoning_effort,
            is_default=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return await _public_for(user)


@router.delete("/settings/llm", response_model=LlmSettingsOut)
async def clear_llm_settings(user: dict = Depends(get_current_user)):
    await delete_user_config(user["id"])
    return await _public_for(user)


@router.post("/settings/llm/test", response_model=LlmTestOut)
async def test_llm_settings(
    body: LlmSettingsUpdate,
    user: dict = Depends(get_current_user),
):
    _require_byok()
    spec = get_provider(body.provider)
    if not spec:
        raise HTTPException(status_code=400, detail="不支持的模型服务商")

    existing = await get_user_config(user["id"], spec.id)
    api_key = (body.api_key or "").strip() or (existing["api_key"] if existing else "")
    if not api_key and spec.id != "ollama":
        raise HTTPException(status_code=400, detail="请先填写 API Key")

    try:
        base_url = resolve_base_url(spec, body.base_url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    model = body.model.strip()

    started = time.perf_counter()
    try:
        if spec.kind == "anthropic":
            llm = AnthropicLLM(api_key, base_url, model)
        else:
            llm = OpenAICompatibleLLM(api_key, base_url, model)
        async with asyncio.timeout(15):
            async for _ in llm.astream(
                [{"role": "user", "content": "Reply with OK only."}],
                max_tokens=8,
            ):
                break
        elapsed = int((time.perf_counter() - started) * 1000)
        return LlmTestOut(
            ok=True, model=model, latency_ms=elapsed,
            message="连接成功，已收到模型响应",
        )
    except TimeoutError:
        elapsed = int((time.perf_counter() - started) * 1000)
        return LlmTestOut(
            ok=False, model=model, latency_ms=elapsed,
            message="连接超时：部分思考模型首 token 较慢，可先保存后在对话中验证",
        )
    except Exception as exc:  # noqa: BLE001
        elapsed = int((time.perf_counter() - started) * 1000)
        # Replace the literal key first: redact_text only knows key-shaped
        # patterns, so a provider echoing an opaque key would otherwise leak.
        detail = str(exc).replace(api_key, "[REDACTED]") if api_key else str(exc)
        return LlmTestOut(
            ok=False, model=model, latency_ms=elapsed,
            message=redact_text(detail)[:300],
        )

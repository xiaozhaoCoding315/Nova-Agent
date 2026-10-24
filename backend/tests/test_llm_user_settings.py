"""BYOK: per-user keys are encrypted, masked, retained on edits and preferred."""
from unittest.mock import AsyncMock

import pytest

from app.api.v1.settings_llm import _public_view
from app.config import settings
from app.core.llm import factory, user_settings


def test_key_encryption_roundtrip_and_tamper_detection():
    token = user_settings.encrypt_key("sk-secret-value")
    assert token != "sk-secret-value"
    assert user_settings.decrypt_key(token) == "sk-secret-value"
    with pytest.raises(ValueError):
        user_settings.decrypt_key(token[:-4] + "AAAA")


def test_base_url_validation_rejects_non_http_and_metadata():
    preset = user_settings.provider_by_id("custom")
    with pytest.raises(ValueError):
        user_settings._clean_base_url(preset, "ftp://example.com")
    with pytest.raises(ValueError):
        user_settings._clean_base_url(preset, "http://169.254.169.254/v1")


@pytest.mark.asyncio
async def test_save_keeps_existing_key_when_not_retyped(monkeypatch):
    stored: dict[int, tuple] = {}

    async def fake_query(_sql, params):
        row = stored.get(params[0])
        return [row] if row else []

    async def fake_execute(_sql, params):
        user_id, provider, base_url, model, encrypted = params[:5]
        stored[user_id] = (provider, base_url, model, encrypted, None, "", None)
        return []

    monkeypatch.setattr(user_settings, "query", fake_query)
    monkeypatch.setattr(user_settings, "execute", fake_execute)

    first = await user_settings.save_user_config(
        7, provider="dashscope", model="qwen3.8-max", api_key="sk-first-key"
    )
    assert first["api_key"] == "sk-first-key"
    assert first["key_hint"].endswith("key")

    second = await user_settings.save_user_config(
        7, provider="dashscope", model="qwen3.5-plus", api_key=None
    )
    assert second["api_key"] == "sk-first-key"
    assert second["model"] == "qwen3.5-plus"

    with pytest.raises(ValueError):
        await user_settings.save_user_config(7, provider="unknown", model="x", api_key="k")


def test_public_view_never_returns_the_raw_key():
    view = _public_view({
        "provider": "dashscope",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen3.8-max",
        "api_key": "sk-very-secret",
        "key_hint": "••••cret",
        "updated_at": None,
    }, {"role": "demo", "is_guest": False})
    payload = view.model_dump()
    assert "api_key" not in payload
    assert payload["configured"] is True
    assert payload["source"] == "user"
    assert payload["key_hint"] == "••••cret"


@pytest.mark.asyncio
async def test_factory_prefers_user_config_and_uses_session_model(monkeypatch):
    monkeypatch.setattr(factory, "get_user_config", AsyncMock(return_value={
        "provider": "deepseek",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "api_key": "sk-user",
        "key_hint": "••••user",
    }))

    llm = await factory.get_llm(7, model="deepseek-reasoner")

    assert isinstance(llm, factory.OpenAICompatibleLLM)
    assert llm.model == "deepseek-reasoner"
    assert str(llm.client.base_url).rstrip("/") == "https://api.deepseek.com/v1"


@pytest.mark.asyncio
async def test_server_fallback_can_be_disabled_for_deployments(monkeypatch):
    monkeypatch.setattr(factory, "get_user_config", AsyncMock(return_value=None))
    monkeypatch.setattr(settings, "llm_allow_server_fallback", False)
    monkeypatch.setattr(settings, "dashscope_api_key", "sk-server")

    with pytest.raises(RuntimeError, match="个人 API Key"):
        await factory.get_llm(7)


@pytest.mark.asyncio
async def test_server_chain_still_works_when_fallback_allowed(monkeypatch):
    monkeypatch.setattr(factory, "get_user_config", AsyncMock(return_value=None))
    monkeypatch.setattr(factory, "_fallback_allowed_for", AsyncMock(return_value=True))
    monkeypatch.setattr(settings, "llm_allow_server_fallback", True)
    monkeypatch.setattr(settings, "llm_model_priority", "dashscope")
    monkeypatch.setattr(settings, "dashscope_api_key", "sk-server")

    llm = await factory.get_llm(7)

    assert isinstance(llm, factory.FallbackLLM)
    assert llm.context_window == settings.default_context_window
    assert factory.server_default_model() == settings.dashscope_model


@pytest.mark.asyncio
async def test_server_key_reserved_for_guests_and_admins(monkeypatch):
    """注册用户默认不能用共享 Key；游客与管理员可以。"""
    async def fake_query(_sql, params):
        role, is_guest = fake_query.tier
        return [(role, is_guest)]

    monkeypatch.setattr("app.db.query", fake_query)
    monkeypatch.setattr(settings, "llm_allow_server_fallback", True)

    fake_query.tier = ("demo", False)
    assert await factory._fallback_allowed_for(7) is False

    fake_query.tier = ("demo", True)
    assert await factory._fallback_allowed_for(8) is True

    fake_query.tier = ("admin", False)
    assert await factory._fallback_allowed_for(1) is True

    monkeypatch.setattr(settings, "llm_server_fallback_registered", True)
    fake_query.tier = ("demo", False)
    assert await factory._fallback_allowed_for(7) is True


@pytest.mark.asyncio
async def test_registered_user_without_key_gets_byok_guidance(monkeypatch):
    monkeypatch.setattr(factory, "get_user_config", AsyncMock(return_value=None))
    monkeypatch.setattr(factory, "_fallback_allowed_for", AsyncMock(return_value=False))

    with pytest.raises(RuntimeError, match="个人 API Key"):
        await factory.get_llm(7)


@pytest.mark.asyncio
async def test_fallback_denied_when_db_lookup_fails(monkeypatch):
    """DB 异常时按拒绝处理，防止额度被意外消耗。"""
    async def broken_query(_sql, params):
        raise RuntimeError("db down")

    monkeypatch.setattr("app.db.query", broken_query)
    monkeypatch.setattr(settings, "llm_allow_server_fallback", True)
    assert await factory._fallback_allowed_for(7) is False
    assert await factory._fallback_allowed_for(None) is True  # 系统调用不受限

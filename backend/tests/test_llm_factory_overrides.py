from unittest.mock import AsyncMock

import pytest

from app.core.llm import factory
from app.core.llm.anthropic import AnthropicLLM


def _config(provider: str, model: str) -> dict:
    return {
        "provider": provider,
        "base_url": "https://example.invalid/v1",
        "model": model,
        "api_key": "sk-test",
        "key_hint": "••••test",
        "context_window": 131_072,
        "reasoning_effort": "high",
        "is_default": True,
    }


@pytest.mark.asyncio
async def test_session_overrides_win_over_saved_default(monkeypatch):
    monkeypatch.setattr(
        factory, "get_user_config",
        AsyncMock(side_effect=lambda uid, provider=None: _config(provider or "zhipu", "glm-4.7-flash")),
    )

    llm = await factory.get_llm(
        7,
        overrides={
            "provider": "zhipu",
            "model": "glm-4.6",
            "reasoning_effort": "low",
            "context_window": 64_000,
            "temperature": 0.3,
            "max_tokens": 4096,
        },
    )

    assert isinstance(llm, factory.OpenAICompatibleLLM)
    assert llm.model == "glm-4.6"
    assert llm.reasoning_effort == "low"
    assert llm.temperature == 0.3
    assert llm.max_tokens == 4096
    assert llm.context_window == 64_000


@pytest.mark.asyncio
async def test_missing_provider_override_is_explicit(monkeypatch):
    monkeypatch.setattr(factory, "get_user_config", AsyncMock(return_value=None))

    with pytest.raises(RuntimeError, match="配置该厂商"):
        await factory.get_llm(7, overrides={"provider": "openai"})


@pytest.mark.asyncio
async def test_anthropic_override_builds_native_provider(monkeypatch):
    monkeypatch.setattr(
        factory, "get_user_config",
        AsyncMock(return_value=_config("anthropic", "claude-sonnet-5-5")),
    )

    llm = await factory.get_llm(
        7, overrides={"provider": "anthropic", "reasoning_effort": "medium"},
    )

    assert isinstance(llm, AnthropicLLM)
    assert llm.thinking_budget == 16_384

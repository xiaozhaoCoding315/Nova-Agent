from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.llm import factory
from app.core.llm.anthropic import AnthropicLLM


class _EmptyStream:
    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration


class _FakeCompletions:
    """Records create() kwargs; rejects the ones the predicate dislikes."""

    def __init__(self, reject) -> None:
        self.calls: list[dict] = []
        self._reject = reject

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self._reject(kwargs):
            raise TypeError("unsupported parameter")
        return _EmptyStream()


def _fake_llm(reject=lambda kwargs: False, **kwargs):
    llm = factory.OpenAICompatibleLLM(
        "sk-test", "https://example.invalid/v1", "test-model", **kwargs
    )
    completions = _FakeCompletions(reject)
    llm.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return llm, completions


async def _drain_tools(llm, **kwargs) -> list[dict]:
    return [
        event
        async for event in llm.astream_with_tools(
            [{"role": "user", "content": "hi"}], [], **kwargs
        )
    ]


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
    assert llm.reasoning_effort == "medium"


@pytest.mark.asyncio
async def test_purpose_suppresses_reasoning_effort_for_openai(monkeypatch):
    monkeypatch.setattr(
        factory, "get_user_config",
        AsyncMock(return_value=_config("zhipu", "glm-4.7-flash")),
    )

    llm = await factory.get_llm(
        7, purpose="utility", overrides={"reasoning_effort": "high"},
    )

    assert isinstance(llm, factory.OpenAICompatibleLLM)
    assert llm.reasoning_effort is None


@pytest.mark.asyncio
async def test_purpose_suppresses_reasoning_effort_for_anthropic(monkeypatch):
    monkeypatch.setattr(
        factory, "get_user_config",
        AsyncMock(return_value=_config("anthropic", "claude-sonnet-5-5")),
    )

    llm = await factory.get_llm(
        7, purpose="utility", overrides={"reasoning_effort": "high"},
    )

    assert isinstance(llm, AnthropicLLM)
    assert llm.reasoning_effort is None


def test_context_window_override_wins_over_provider_attribute():
    class Provider:
        context_window = 200_000

    assert factory.resolve_context_window(
        7, Provider(), {"context_window": 64_000}
    ) == 64_000


@pytest.mark.asyncio
async def test_tool_retry_drops_stream_options_first():
    llm, completions = _fake_llm(
        reject=lambda kwargs: "stream_options" in kwargs,
        reasoning_effort="high",
    )

    await _drain_tools(llm)

    assert len(completions.calls) == 2
    assert completions.calls[0]["stream_options"] == {"include_usage": True}
    assert completions.calls[1]["reasoning_effort"] == "high"
    assert "stream_options" not in completions.calls[1]


@pytest.mark.asyncio
async def test_tool_retry_drops_temperature_before_extras():
    llm, completions = _fake_llm(
        reject=lambda kwargs: "stream_options" in kwargs or "temperature" in kwargs,
        reasoning_effort="high",
        temperature=0.2,
        max_tokens=4096,
    )

    await _drain_tools(llm)

    assert len(completions.calls) == 3
    final = completions.calls[-1]
    assert final["reasoning_effort"] == "high"
    assert final["max_tokens"] == 4096
    assert "temperature" not in final


@pytest.mark.asyncio
async def test_tool_retry_ends_on_bare_call_without_duplicates():
    rejected = ("stream_options", "reasoning_effort", "temperature", "max_tokens")
    llm, completions = _fake_llm(
        reject=lambda kwargs: any(key in kwargs for key in rejected),
        reasoning_effort="high",
        temperature=0.2,
        max_tokens=2048,
    )

    await _drain_tools(llm)

    assert len(completions.calls) == 4
    assert set(completions.calls[-1]) == {
        "model", "messages", "tools", "tool_choice", "stream",
    }
    assert len({repr(call) for call in completions.calls}) == len(completions.calls)


@pytest.mark.asyncio
async def test_astream_with_empty_extras_makes_one_call():
    llm, completions = _fake_llm(reject=lambda kwargs: True)

    with pytest.raises(TypeError):
        async for _ in llm.astream([{"role": "user", "content": "hi"}]):
            pass

    assert len(completions.calls) == 1


@pytest.mark.asyncio
async def test_catalog_vision_flag_reaches_openai_provider(monkeypatch):
    monkeypatch.setattr(
        factory, "get_user_config",
        AsyncMock(return_value=_config("openai", "gpt-4o")),
    )
    llm = await factory.get_llm(7, overrides={"provider": "openai"})
    assert isinstance(llm, factory.OpenAICompatibleLLM)
    assert llm.supports_vision is True

    monkeypatch.setattr(
        factory, "get_user_config",
        AsyncMock(return_value=_config("deepseek", "deepseek-chat")),
    )
    llm = await factory.get_llm(7, overrides={"provider": "deepseek"})
    assert llm.supports_vision is False


@pytest.mark.asyncio
async def test_non_vision_openai_provider_strips_image_blocks():
    llm, completions = _fake_llm()
    llm.supports_vision = False
    messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": "看图"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}},
        ],
    }]
    [event async for event in llm.astream_with_tools(messages, [])]
    sent = completions.calls[0]["messages"][0]["content"]
    assert sent[1]["type"] == "text"
    assert "图片已省略" in sent[1]["text"]

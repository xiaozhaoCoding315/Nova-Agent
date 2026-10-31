import pytest
from app.core.llm.fallback import FallbackLLM
from app.core.llm.base import LLMProvider


class FakeLLM(LLMProvider):
    def __init__(self, name, should_fail=False):
        self._name = name
        self._should_fail = should_fail

    async def astream(self, messages):
        if self._should_fail:
            raise RuntimeError(f"{self._name} down")
        yield f"response from {self._name}"


@pytest.mark.asyncio
async def test_fallback_tries_next_on_failure():
    primary = FakeLLM("longcat", should_fail=True)
    secondary = FakeLLM("deepseek")
    fb = FallbackLLM([primary, secondary])

    tokens = []
    async for token in fb.astream([{"role": "user", "content": "hi"}]):
        tokens.append(token)
    assert "response from deepseek" in tokens


@pytest.mark.asyncio
async def test_fallback_uses_first_successful():
    primary = FakeLLM("longcat")
    secondary = FakeLLM("deepseek")
    fb = FallbackLLM([primary, secondary])

    tokens = []
    async for token in fb.astream([{"role": "user", "content": "hi"}]):
        tokens.append(token)
    assert "response from longcat" in tokens


class ToolFake(FakeLLM):
    supports_tools = True

    async def astream_with_tools(self, messages, tools):
        if self._should_fail:
            raise RuntimeError(f"{self._name} down")
        yield {"type": "content", "content": f"tools from {self._name}"}


@pytest.mark.asyncio
async def test_tool_fallback_skips_providers_without_tool_support():
    chat_only = FakeLLM("chat-only")
    capable = ToolFake("capable")
    fb = FallbackLLM([chat_only, capable])

    events = []
    async for event in fb.astream_with_tools([], []):
        events.append(event)
    assert events == [{"type": "content", "content": "tools from capable"}]


@pytest.mark.asyncio
async def test_tool_fallback_refuses_to_degrade_to_chat():
    fb = FallbackLLM([FakeLLM("chat-only")])
    with pytest.raises(RuntimeError, match="支持工具调用"):
        async for _ in fb.astream_with_tools([], []):
            pass

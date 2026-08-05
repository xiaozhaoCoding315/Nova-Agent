import pytest
from unittest.mock import AsyncMock, patch
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

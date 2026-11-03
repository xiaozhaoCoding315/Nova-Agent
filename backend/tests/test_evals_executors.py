"""Executor behavior for scripted and live modes."""
import pytest

from evals.executors import LiveExecutor, ScriptedExecutor, ScriptExhausted


@pytest.mark.asyncio
async def test_scripted_executor_advances_and_captures_deep_copies():
    messages = [{"role": "user", "content": "hi"}]
    executor = ScriptedExecutor((
        ({"type": "content", "content": "first"},),
        ({"type": "content", "content": "second"},),
    ))
    first = []
    async for event in executor.astream_with_tools(messages, []):
        first.append(event)
    messages[0]["content"] = "mutated"

    assert first == [{"type": "content", "content": "first"}]
    assert executor.llm_messages[0][0]["content"] == "hi"

    second = []
    async for event in executor.astream_with_tools(messages, []):
        second.append(event)
    assert second == [{"type": "content", "content": "second"}]

    with pytest.raises(ScriptExhausted, match="超过脚本轮次"):
        async for _ in executor.astream_with_tools(messages, []):
            pass


class _InnerLLM:
    supports_vision = True
    context_window = 4096

    def __init__(self):
        self.seen = []

    async def astream_with_tools(self, messages, tools):
        self.seen.append(messages)
        yield {"type": "content", "content": "live"}


@pytest.mark.asyncio
async def test_live_executor_proxies_attributes_and_captures():
    inner = _InnerLLM()
    executor = LiveExecutor(inner)
    assert executor.supports_vision is True
    assert executor.context_window == 4096

    messages = [{"role": "user", "content": "hi"}]
    events = []
    async for event in executor.astream_with_tools(messages, []):
        events.append(event)
    messages[0]["content"] = "mutated"

    assert events == [{"type": "content", "content": "live"}]
    assert executor.llm_messages[0][0]["content"] == "hi"
    assert inner.seen[0][0]["content"] == "hi"

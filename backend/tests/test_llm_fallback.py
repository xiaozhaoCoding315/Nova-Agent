import pytest

from app.core.agent.image_input import is_image_rejection
from app.core.llm.base import LLMProvider
from app.core.llm.fallback import FallbackLLM


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
    primary = FakeLLM("zhipu", should_fail=True)
    secondary = FakeLLM("deepseek")
    fb = FallbackLLM([primary, secondary])

    tokens = []
    async for token in fb.astream([{"role": "user", "content": "hi"}]):
        tokens.append(token)
    assert "response from deepseek" in tokens


@pytest.mark.asyncio
async def test_fallback_uses_first_successful():
    primary = FakeLLM("zhipu")
    secondary = FakeLLM("deepseek")
    fb = FallbackLLM([primary, secondary])

    tokens = []
    async for token in fb.astream([{"role": "user", "content": "hi"}]):
        tokens.append(token)
    assert "response from zhipu" in tokens


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


class VisionToolFake(ToolFake):
    supports_vision = True


class VisionChatFake(FakeLLM):
    supports_vision = True


@pytest.mark.asyncio
async def test_fallback_strips_images_for_text_only_provider():
    seen = {}

    class Capture(ToolFake):
        supports_vision = False

        async def astream_with_tools(self, messages, tools):
            seen["messages"] = messages
            yield {"type": "content", "content": "ok"}

    image_message = {
        "role": "user",
        "content": [
            {"type": "text", "text": "看图"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}},
        ],
    }
    fb = FallbackLLM([Capture("text")])
    async for _ in fb.astream_with_tools([image_message], []):
        pass

    blocks = seen["messages"][0]["content"]
    assert blocks[0] == {"type": "text", "text": "看图"}
    assert blocks[1]["type"] == "text"
    assert "图片已省略" in blocks[1]["text"]
    assert image_message["content"][1]["type"] == "image_url"


@pytest.mark.asyncio
async def test_fallback_keeps_images_for_vision_provider():
    seen = {}

    class Capture(VisionToolFake):
        async def astream_with_tools(self, messages, tools):
            seen["messages"] = messages
            yield {"type": "content", "content": "ok"}

    image_message = {
        "role": "user",
        "content": [
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}},
        ],
    }
    fb = FallbackLLM([Capture("vision")])
    async for _ in fb.astream_with_tools([image_message], []):
        pass
    assert seen["messages"][0]["content"][0]["type"] == "image_url"


@pytest.mark.asyncio
async def test_fallback_astream_strips_images_for_text_only_provider():
    seen = {}

    class Capture(FakeLLM):
        supports_vision = False

        async def astream(self, messages):
            seen["messages"] = messages
            yield "ok"

    image_message = {
        "role": "user",
        "content": [
            {"type": "text", "text": "看图"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}},
        ],
    }
    fb = FallbackLLM([Capture("text")])
    tokens = [token async for token in fb.astream([image_message])]
    assert tokens == ["ok"]

    blocks = seen["messages"][0]["content"]
    assert blocks[0] == {"type": "text", "text": "看图"}
    assert blocks[1]["type"] == "text"
    assert "图片已省略" in blocks[1]["text"]
    # The caller's original messages are not mutated.
    assert image_message["content"][1]["type"] == "image_url"


@pytest.mark.asyncio
async def test_fallback_astream_keeps_images_for_vision_provider():
    seen = {}

    class Capture(VisionChatFake):
        async def astream(self, messages):
            seen["messages"] = messages
            yield "ok"

    image_message = {
        "role": "user",
        "content": [
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}},
        ],
    }
    fb = FallbackLLM([Capture("vision")])
    async for _ in fb.astream([image_message]):
        pass
    assert seen["messages"][0]["content"][0]["type"] == "image_url"


def test_fallback_supports_vision_aggregates_chain():
    mixed = FallbackLLM([FakeLLM("text"), VisionChatFake("vision")])
    text_only = FallbackLLM([FakeLLM("a"), FakeLLM("b")])
    assert mixed.supports_vision is True
    assert text_only.supports_vision is False


class ImageRejectingToolFake:
    supports_tools = True
    supports_vision = True

    def __init__(self):
        self.exc = RuntimeError("OpenAI API 400: invalid image content")

    async def astream_with_tools(self, messages, tools):
        raise self.exc
        yield  # pragma: no cover — keeps this an async generator


class PlainFailureToolFake:
    supports_tools = True
    supports_vision = False

    def __init__(self):
        self.exc = RuntimeError("secondary provider down")

    async def astream_with_tools(self, messages, tools):
        raise self.exc
        yield  # pragma: no cover — keeps this an async generator


@pytest.mark.asyncio
async def test_fallback_chains_image_rejection_cause():
    image_provider = ImageRejectingToolFake()
    failing_provider = PlainFailureToolFake()
    fb = FallbackLLM([image_provider, failing_provider])

    with pytest.raises(RuntimeError) as exc_info:
        async for _ in fb.astream_with_tools([], []):
            pass

    assert str(exc_info.value) == "All LLM providers failed"
    assert is_image_rejection(exc_info.value) is True
    assert exc_info.value.__cause__ is image_provider.exc


# ---------- provider health ----------

class NamedToolFake(ToolFake):
    def __init__(self, name, should_fail=False):
        super().__init__(name, should_fail)
        self.provider_id = name
        self.calls = 0

    async def astream_with_tools(self, messages, tools):
        self.calls += 1
        if self._should_fail:
            raise ConnectionError(f"{self._name} down")
        yield {"type": "content", "content": f"tools from {self._name}"}


@pytest.fixture(autouse=True)
def _clean_health():
    from app.core.llm import health

    health.reset()
    yield
    health.reset()


@pytest.mark.asyncio
async def test_dead_provider_is_skipped_after_repeated_failures():
    """A downed primary must stop costing a full timeout on every request."""
    from app.core.llm import health

    primary = NamedToolFake("zhipu", should_fail=True)
    backup = NamedToolFake("agnes")
    fb = FallbackLLM([primary, backup])

    for _ in range(health.FAILURE_THRESHOLD):
        async for _event in fb.astream_with_tools([], []):
            pass

    assert primary.calls == health.FAILURE_THRESHOLD
    async for _event in fb.astream_with_tools([], []):
        pass
    assert primary.calls == health.FAILURE_THRESHOLD, "open provider must be skipped"
    assert backup.calls == health.FAILURE_THRESHOLD + 1


@pytest.mark.asyncio
async def test_success_clears_provider_health():
    from app.core.llm import health

    flaky = NamedToolFake("dashscope", should_fail=True)
    backup = NamedToolFake("agnes")
    fb = FallbackLLM([flaky, backup])

    async for _event in fb.astream_with_tools([], []):
        pass
    assert health.failures(flaky) == 1
    health.reset()

    flaky._should_fail = False
    async for _event in fb.astream_with_tools([], []):
        pass
    assert health.is_available("dashscope") is True
    assert health.failures(flaky) == 0
    assert backup.calls == 1, "a healthy primary must not reach the backup"


@pytest.mark.asyncio
async def test_fallback_still_uses_open_providers_when_all_are_open():
    """Skipping every provider would be worse than trying a recovering one."""
    from app.core.llm import health

    primary = NamedToolFake("zhipu", should_fail=True)
    backup = NamedToolFake("agnes")
    fb = FallbackLLM([primary, backup])

    for _ in range(health.FAILURE_THRESHOLD):
        async for _event in fb.astream_with_tools([], []):
            pass
    health.mark_down("agnes", seconds=600)

    events = [event async for event in fb.astream_with_tools([], [])]
    assert events and events[0]["content"] == "tools from agnes"


@pytest.mark.asyncio
async def test_usage_reports_which_provider_answered():
    class Reporting(NamedToolFake):
        async def astream_with_tools(self, messages, tools):
            yield {"type": "content", "content": "hi"}
            yield {"type": "usage", "usage": {
                "model": "m", "prompt_tokens": 3, "completion_tokens": 1,
                "provider": self.provider_id,
            }}

    fb = FallbackLLM([Reporting("agnes")])
    events = [event async for event in fb.astream_with_tools([], [])]
    usage = next(e["usage"] for e in events if e["type"] == "usage")
    assert usage["provider"] == "agnes"

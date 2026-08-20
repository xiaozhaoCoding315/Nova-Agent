from abc import ABC, abstractmethod


class LLMProvider(ABC):
    @abstractmethod
    async def astream(self, messages: list[dict]) -> any:
        """Yield string tokens."""
        ...

    async def astream_with_tools(self, messages: list[dict], tools: list[dict]):
        """Yield event dicts for function-calling conversations.

        Event protocol (consumed by the chat loop):
          {"type": "content",    "content": str}
          {"type": "tool_calls", "tool_calls": [{"id", "name", "arguments"}]}
          {"type": "finish",     "finish_reason": str}

        Default implementation: providers without native tool support degrade
        gracefully to plain streaming, so FallbackLLM can always try them.
        """
        async for token in self.astream(messages):
            yield {"type": "content", "content": token}
        yield {"type": "finish", "finish_reason": "stop"}

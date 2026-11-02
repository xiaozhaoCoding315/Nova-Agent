import structlog

from app.core.agent.image_input import is_image_rejection, strip_image_blocks
from app.core.llm.base import LLMProvider

logger = structlog.get_logger()


def _messages_for(provider, messages: list[dict]) -> list[dict]:
    return (
        messages
        if getattr(provider, "supports_vision", False)
        else strip_image_blocks(messages)
    )


class FallbackLLM(LLMProvider):
    def __init__(self, providers: list[LLMProvider]):
        self.providers = providers

    @property
    def supports_vision(self) -> bool:
        return any(
            getattr(provider, "supports_vision", False)
            for provider in self.providers
        )

    async def astream(self, messages: list[dict], **kwargs):
        last_exc: Exception | None = None
        image_exc: Exception | None = None
        for provider in self.providers:
            try:
                provider_messages = _messages_for(provider, messages)
                async for token in provider.astream(provider_messages, **kwargs):
                    yield token
                return  # success — stop chain
            except Exception as e:
                if is_image_rejection(e):
                    image_exc = image_exc or e
                last_exc = e
                logger.warning("LLM provider failed, trying next",
                             provider=type(provider).__name__, error=str(e))
                continue
        cause = image_exc or last_exc
        if cause is not None:
            raise RuntimeError("All LLM providers failed") from cause
        raise RuntimeError("All LLM providers failed")

    async def astream_with_tools(self, messages: list[dict], tools: list[dict], **kwargs):
        """Provider-chain function calling.

        Same degradation semantics as astream, with one refinement: once any
        event has been yielded downstream we can no longer switch providers
        (the answer would be duplicated), so mid-stream failures propagate.
        Only providers with native tool support participate — a provider that
        ignores ``tools`` would silently degrade the coding loop to chat.
        """
        providers = [p for p in self.providers if getattr(p, "supports_tools", False)]
        if not providers:
            raise RuntimeError("没有支持工具调用的 LLM provider，已拒绝退化")
        last_exc: Exception | None = None
        image_exc: Exception | None = None
        for provider in providers:
            provider_messages = _messages_for(provider, messages)
            yielded = False
            try:
                async for event in provider.astream_with_tools(
                    provider_messages, tools, **kwargs
                ):
                    yielded = True
                    yield event
                return  # success — stop chain
            except Exception as e:
                if yielded:
                    logger.error("LLM provider failed mid-stream, aborting tool call chain",
                                 provider=type(provider).__name__, error=str(e))
                    raise
                if is_image_rejection(e):
                    image_exc = image_exc or e
                last_exc = e
                logger.warning("LLM provider failed, trying next",
                             provider=type(provider).__name__, error=str(e))
                continue
        cause = image_exc or last_exc
        if cause is not None:
            raise RuntimeError("All LLM providers failed") from cause
        raise RuntimeError("All LLM providers failed")

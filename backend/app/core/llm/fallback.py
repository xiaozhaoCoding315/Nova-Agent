import structlog

from app.core.agent.image_input import strip_image_blocks
from app.core.llm.base import LLMProvider

logger = structlog.get_logger()


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
        for provider in self.providers:
            try:
                provider_messages = (
                    messages
                    if getattr(provider, "supports_vision", False)
                    else strip_image_blocks(messages)
                )
                async for token in provider.astream(provider_messages, **kwargs):
                    yield token
                return  # success — stop chain
            except Exception as e:
                logger.warning("LLM provider failed, trying next",
                             provider=type(provider).__name__, error=str(e))
                continue
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
        for provider in providers:
            provider_messages = (
                messages
                if getattr(provider, "supports_vision", False)
                else strip_image_blocks(messages)
            )
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
                logger.warning("LLM provider failed, trying next",
                             provider=type(provider).__name__, error=str(e))
                continue
        raise RuntimeError("All LLM providers failed")

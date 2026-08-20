import structlog
from app.core.llm.base import LLMProvider

logger = structlog.get_logger()


class FallbackLLM(LLMProvider):
    def __init__(self, providers: list[LLMProvider]):
        self.providers = providers

    async def astream(self, messages: list[dict]):
        for provider in self.providers:
            try:
                async for token in provider.astream(messages):
                    yield token
                return  # success — stop chain
            except Exception as e:
                logger.warning("LLM provider failed, trying next",
                             provider=type(provider).__name__, error=str(e))
                continue
        raise RuntimeError("All LLM providers failed")

    async def astream_with_tools(self, messages: list[dict], tools: list[dict]):
        """Provider-chain function calling.

        Same degradation semantics as astream, with one refinement: once any
        event has been yielded downstream we can no longer switch providers
        (the answer would be duplicated), so mid-stream failures propagate.
        Providers without native tool support degrade to plain content via
        the base-class default, which still counts as a usable answer.
        """
        for provider in self.providers:
            yielded = False
            try:
                async for event in provider.astream_with_tools(messages, tools):
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

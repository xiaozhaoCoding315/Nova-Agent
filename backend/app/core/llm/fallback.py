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

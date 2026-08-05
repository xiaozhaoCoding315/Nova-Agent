from abc import ABC, abstractmethod


class LLMProvider(ABC):
    @abstractmethod
    async def astream(self, messages: list[dict]) -> any:
        """Yield string tokens."""
        ...

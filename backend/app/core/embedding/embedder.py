from abc import ABC, abstractmethod
from openai import AsyncOpenAI
from app.config import settings


class Embedder(ABC):
    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        ...


class OpenAIEmbedder(Embedder):
    def __init__(self):
        self.client = AsyncOpenAI(
            api_key=settings.dashscope_api_key,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        self.model = settings.embedding_model

    async def embed(self, texts: list[str], batch_size: int = 10) -> list[list[float]]:
        """Embed texts with batching — DashScope limits to 10 per request."""
        all_embeddings = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            resp = await self.client.embeddings.create(model=self.model, input=batch)
            all_embeddings.extend([d.embedding for d in resp.data])
        return all_embeddings


def get_embedder() -> Embedder:
    return OpenAIEmbedder()

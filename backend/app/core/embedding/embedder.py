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
            base_url=settings.dashscope_base_url,
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


_embedder: "OpenAIEmbedder | None" = None


def get_embedder() -> "Embedder":
    global _embedder
    if not settings.dashscope_api_key:
        raise RuntimeError("DASHSCOPE_API_KEY not configured — dense retrieval unavailable")
    if _embedder is None:
        _embedder = OpenAIEmbedder()
    return _embedder

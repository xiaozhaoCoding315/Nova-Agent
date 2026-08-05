import pytest
from app.core.embedding.embedder import Embedder, get_embedder


class DummyEmbedder(Embedder):
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3] for _ in texts]


def test_embedder_returns_correct_dimensions():
    e = DummyEmbedder()
    vectors = e.embed(["hello", "world"])
    assert len(vectors) == 2
    assert len(vectors[0]) == 3


def test_factory_returns_embedder():
    # Will fail until factory is implemented
    from app.core.embedding.embedder import get_embedder
    e = get_embedder()
    assert e is not None

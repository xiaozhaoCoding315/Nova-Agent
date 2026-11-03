from app.core.embedding.embedder import Embedder, get_embedder


class DummyEmbedder(Embedder):
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3] for _ in texts]


def test_embedder_returns_correct_dimensions():
    e = DummyEmbedder()
    vectors = e.embed(["hello", "world"])
    assert len(vectors) == 2
    assert len(vectors[0]) == 3


def test_factory_returns_embedder(monkeypatch):
    from app.config import settings
    from app.core.embedding import embedder as embedder_module

    monkeypatch.setattr(settings, "dashscope_api_key", "sk-test")
    monkeypatch.setattr(embedder_module, "_embedder", None)

    e = get_embedder()
    assert e is not None

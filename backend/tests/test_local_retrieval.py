"""Local mode: retrieval degrades to keyword-only and Qdrant stays untouched."""
from unittest.mock import AsyncMock

import pytest

from app.config import settings
from app.core.rag import dense, retriever
from app.db import init_db
from app.models.domain import RetrievedChunk


@pytest.mark.asyncio
async def test_dense_search_short_circuits_without_embeddings(monkeypatch):
    monkeypatch.setattr(settings, "nova_mode", "local")

    def boom():
        raise AssertionError("embedder must not be constructed in local mode")

    monkeypatch.setattr(dense, "get_embedder", boom)
    assert await dense.dense_search("query", repo_ids=["00000000-0000-0000-0000-000000000001"]) == []


@pytest.mark.asyncio
async def test_index_embedding_is_skipped_in_local_mode(monkeypatch):
    from app.core.indexing import pipeline

    monkeypatch.setattr(settings, "nova_mode", "local")
    constructed = False

    def boom():
        nonlocal constructed
        constructed = True
        raise AssertionError("embedder must not be constructed during local indexing")

    monkeypatch.setattr("app.core.embedding.embedder.get_embedder", boom)
    assert await pipeline._embed_and_upload(
        "00000000-0000-0000-0000-000000000001", 1,
        [(1, {"content": "def f(): pass"}, "hash")],
    ) == 0
    assert constructed is False


@pytest.mark.asyncio
async def test_retrieve_uses_keyword_only_in_local_mode(monkeypatch):
    called = {"dense": 0, "keyword": 0}

    async def fake_dense(*args, **kwargs):
        called["dense"] += 1
        return []

    async def fake_keyword(*args, **kwargs):
        called["keyword"] += 1
        return [RetrievedChunk(
            id="c1", content="def handler(): pass", path="app.py",
            line_start=10, line_end=12, lang="python", score_type="keyword", score=1.0,
        )]

    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(retriever, "dense_search", fake_dense)
    monkeypatch.setattr(retriever, "keyword_search", fake_keyword)
    hits = await retriever.retrieve(
        "handler", top_k=5, repo_ids=["00000000-0000-0000-0000-000000000001"]
    )
    assert called == {"dense": 0, "keyword": 1}
    assert hits[0].path == "app.py"
    assert hits[0].line_start == 10
    assert hits[0].score_type == "keyword"


@pytest.mark.asyncio
async def test_mode_endpoint_local(monkeypatch):
    from app.api.v1 import status as status_api

    monkeypatch.setattr(settings, "nova_mode", "local")
    info = await status_api.mode()
    assert info.local is True
    assert info.auth == "none"
    assert info.features.host_executor is True
    assert info.features.isolation == "none"
    assert info.features.semantic_search is False
    assert info.features.jobs_concurrency == 1
    assert info.features.registration is False


@pytest.mark.asyncio
async def test_mode_endpoint_local_reports_configured_data_dir(monkeypatch, tmp_path):
    from app.api.v1 import status as status_api

    data_dir = tmp_path / "NovaData"
    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(settings, "nova_data_dir", str(data_dir))
    info = await status_api.mode()
    assert info.data_dir == str(data_dir.resolve())


@pytest.mark.asyncio
async def test_mode_endpoint_local_without_data_dir_reports_empty(monkeypatch):
    from app.api.v1 import status as status_api

    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(settings, "nova_data_dir", "")
    info = await status_api.mode()
    assert info.data_dir == ""


@pytest.mark.asyncio
async def test_health_local_does_not_report_qdrant_failure(monkeypatch):
    from app.api.v1 import status as status_api

    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(status_api, "_check_postgres", AsyncMock(return_value="ok"))
    monkeypatch.setattr(status_api, "_check_local_llm", AsyncMock(return_value="ok: local user credential"))
    monkeypatch.setattr(status_api, "_check_sandbox", AsyncMock(return_value={"available": True, "isolation": "none"}))
    result = await status_api.health()
    assert result.status == "ok"
    assert result.components["qdrant"] == "disabled: local mode"
    assert result.components["embedding"] == "disabled: local mode"
    assert result.components["sandbox"]["isolation"] == "none"


@pytest.mark.asyncio
async def test_init_all_local_skips_qdrant_and_seeds_local_user(monkeypatch):
    from app.core.security import auth

    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(init_db, "check_connectivity", AsyncMock(return_value={"postgres": "connected"}))
    monkeypatch.setattr(init_db, "init_postgres", AsyncMock(return_value="already_exists"))
    monkeypatch.setattr(
        "app.core.storage.user_storage.migrate_legacy_repos",
        AsyncMock(side_effect=AssertionError("must not migrate legacy cloud repos")),
    )
    monkeypatch.setattr(
        init_db, "init_qdrant",
        AsyncMock(side_effect=AssertionError("must not init qdrant in local mode")),
    )
    monkeypatch.setattr(auth, "ensure_local_user", AsyncMock(return_value={"username": "local"}))
    result = await init_db.init_all()
    assert result["qdrant"].startswith("skipped")
    assert result["qdrant_payload"].startswith("skipped")
    assert result["storage"] == "skipped: local mode"
    assert result["users"] == "local: local"


class _FakeConn:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self):
        return self

    def execute(self, *args, **kwargs):
        return None

    def fetchone(self):
        return (1,)


@pytest.mark.asyncio
async def test_check_connectivity_skips_qdrant_socket(monkeypatch):
    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(settings, "embeddings_enabled", False)
    monkeypatch.setattr(init_db.psycopg, "connect", lambda *a, **k: _FakeConn())
    monkeypatch.setattr(
        "qdrant_client.QdrantClient",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not construct QdrantClient")),
    )
    status = await init_db.check_connectivity()
    assert status["postgres"] == "connected"
    assert status["qdrant"].startswith("skipped")


# ---------- Additional guards: Qdrant is never touched without embeddings ----------


@pytest.mark.asyncio
async def test_dense_search_never_builds_a_qdrant_client_without_embeddings(monkeypatch):
    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(
        "app.db.qdrant.get_client",
        lambda: (_ for _ in ()).throw(AssertionError("must not construct QdrantClient")),
    )
    assert await dense.dense_search("query", repo_ids=["00000000-0000-0000-0000-000000000001"]) == []


@pytest.mark.asyncio
async def test_retrieve_uses_both_legs_in_server_mode(monkeypatch):
    called = {"dense": 0, "keyword": 0}

    async def fake_dense(*args, **kwargs):
        called["dense"] += 1
        return [RetrievedChunk(id="d1", content="x", path="a.py", score_type="dense")]

    async def fake_keyword(*args, **kwargs):
        called["keyword"] += 1
        return [RetrievedChunk(id="k1", content="x", path="b.py", score_type="keyword")]

    monkeypatch.setattr(settings, "nova_mode", "server")
    monkeypatch.setattr(settings, "embeddings_enabled", True)
    monkeypatch.setattr(retriever, "dense_search", fake_dense)
    monkeypatch.setattr(retriever, "keyword_search", fake_keyword)
    hits = await retriever.retrieve(
        "x", top_k=5, repo_ids=["00000000-0000-0000-0000-000000000001"]
    )
    assert called == {"dense": 1, "keyword": 1}
    assert {hit.id for hit in hits} == {"d1", "k1"}


@pytest.mark.asyncio
async def test_mode_endpoint_server(monkeypatch):
    from app.api.v1 import status as status_api

    monkeypatch.setattr(settings, "nova_mode", "server")
    monkeypatch.setattr(settings, "embeddings_enabled", True)
    monkeypatch.setattr(settings, "registration_mode", "open")
    info = await status_api.mode()
    assert info.mode == "server"
    assert info.local is False
    assert info.auth == "login"
    assert info.features.host_executor is False
    assert info.features.isolation == "container"
    assert info.features.sandbox == "docker"
    assert info.features.semantic_search is True
    assert info.features.registration is True
    assert info.data_dir == ""


def test_local_data_dir_is_empty_in_server_mode_even_when_configured(monkeypatch, tmp_path):
    from app.api.v1 import status as status_api

    monkeypatch.setattr(settings, "nova_mode", "server")
    monkeypatch.setattr(settings, "nova_data_dir", str(tmp_path / "NovaData"))
    assert status_api._local_data_dir() == ""


def test_mode_endpoint_over_http_without_auth_in_local_mode(monkeypatch, tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.v1 import status as status_api

    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(settings, "nova_data_dir", str(tmp_path / "NovaData"))

    app = FastAPI()
    app.include_router(status_api.router, prefix="/api/v1")
    # No ``with`` block: no lifespan runs, so no DB init is attempted.
    response = TestClient(app).get("/api/v1/status/mode")

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "local"
    assert body["local"] is True
    assert body["auth"] == "none"
    assert body["data_dir"] == str((tmp_path / "NovaData").resolve())


@pytest.mark.asyncio
async def test_delete_file_data_skips_qdrant_without_embeddings(monkeypatch):
    from app.core.indexing import pipeline

    monkeypatch.setattr(settings, "nova_mode", "local")
    executed: list[tuple] = []

    async def fake_query(_sql, _params):
        return [(11,), (12,)]

    async def fake_execute(sql, params):
        executed.append((sql, params))
        return []

    deleted: list[list[int]] = []

    async def fake_delete(ids):
        deleted.append(list(ids))
        return len(ids)

    monkeypatch.setattr(pipeline, "query", fake_query)
    monkeypatch.setattr(pipeline, "execute", fake_execute)
    monkeypatch.setattr("app.db.qdrant.delete_point_ids", fake_delete)

    await pipeline._delete_file_data(5)

    assert deleted == []
    assert "DELETE FROM repo_files" in executed[0][0]
    assert executed[0][1] == (5,)


@pytest.mark.asyncio
async def test_delete_repo_skips_qdrant_without_embeddings(monkeypatch, tmp_path):
    from app.core.indexing import pipeline

    monkeypatch.setattr(settings, "nova_mode", "local")

    async def fake_get(repo_id, user_id):
        return {"id": repo_id, "user_id": user_id, "origin": "local",
                "root_path": str(tmp_path)}

    executed: list[str] = []

    async def fake_execute(sql, _params):
        executed.append(sql)
        return []

    async def fake_cleanup(*_args, **_kwargs):
        return {}

    deleted: list[str] = []

    async def fake_delete(repo_id):
        deleted.append(repo_id)

    monkeypatch.setattr(pipeline, "get_repo", fake_get)
    monkeypatch.setattr(pipeline, "execute", fake_execute)
    monkeypatch.setattr("app.core.deploy.service.cleanup_repo_resources", fake_cleanup)
    monkeypatch.setattr("app.db.qdrant.delete_repo_points", fake_delete)

    assert await pipeline.delete_repo("00000000-0000-0000-0000-000000000001", 1) is True
    assert any("DELETE FROM repos" in sql for sql in executed)
    assert deleted == []


@pytest.mark.asyncio
async def test_index_repo_force_skips_qdrant_without_embeddings(monkeypatch, tmp_path):
    from app.core.indexing import pipeline

    monkeypatch.setattr(settings, "nova_mode", "local")

    async def fake_get(repo_id):
        return {"id": repo_id, "user_id": 1, "name": "empty",
                "root_path": str(tmp_path), "origin": "local"}

    executed: list[str] = []

    async def fake_execute(sql, _params):
        executed.append(sql)
        return []

    async def fake_query(sql, _params):
        if "COUNT(*)" in sql:
            return [(0,)]
        return []

    deleted: list[str] = []

    async def fake_delete(repo_id):
        deleted.append(repo_id)

    monkeypatch.setattr(pipeline, "get_repo", fake_get)
    monkeypatch.setattr(pipeline, "execute", fake_execute)
    monkeypatch.setattr(pipeline, "query", fake_query)
    monkeypatch.setattr("app.db.qdrant.delete_repo_points", fake_delete)

    await pipeline.index_repo("00000000-0000-0000-0000-000000000001", force=True)
    assert any("DELETE FROM repo_files" in sql for sql in executed)
    assert any("status = 'ready'" in sql for sql in executed)
    assert deleted == []


@pytest.mark.asyncio
async def test_purge_user_resources_skips_qdrant_without_embeddings(monkeypatch):
    from app.core import account_cleanup

    monkeypatch.setattr(settings, "nova_mode", "local")

    async def fake_query(_sql, _params):
        return [("repo-1",)]

    deleted: list[str] = []

    async def fake_delete(repo_id):
        deleted.append(repo_id)

    monkeypatch.setattr(account_cleanup, "query", fake_query)
    monkeypatch.setattr(account_cleanup, "execute", AsyncMock())
    monkeypatch.setattr(account_cleanup, "cleanup_user_storage", AsyncMock())
    monkeypatch.setattr("app.core.deploy.service.cleanup_repo_resources", AsyncMock(return_value={}))
    monkeypatch.setattr("app.db.qdrant.delete_repo_points", fake_delete)

    result = await account_cleanup.purge_user_resources(7)

    assert deleted == []
    assert result["repos"] == 1
    assert result["vectors"] == 0

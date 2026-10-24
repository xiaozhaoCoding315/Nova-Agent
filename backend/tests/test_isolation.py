"""Cross-resource isolation helpers: ledger, Qdrant payload and account purge."""
from unittest.mock import AsyncMock

import pytest

from app.core import account_cleanup
from app.core.deploy import ledger
from app.db import qdrant


@pytest.mark.asyncio
async def test_ledger_queries_are_user_scoped(monkeypatch):
    query = AsyncMock(return_value=[])
    monkeypatch.setattr(ledger, "query", query)

    assert await ledger.get(7, "same-key") is None
    sql, params = query.await_args.args
    assert "user_id = %s AND idempotency_key = %s" in sql
    assert params == (7, "same-key")

    execute = AsyncMock()
    monkeypatch.setattr(ledger, "execute", execute)
    await ledger.finish(7, "same-key", "succeeded")
    sql, params = execute.await_args.args
    assert "user_id = %s AND idempotency_key = %s" in sql
    assert params[-2:] == (7, "same-key")


@pytest.mark.asyncio
async def test_qdrant_backfill_sets_user_payload(monkeypatch):
    calls = {}

    class FakeClient:
        def set_payload(self, **kwargs):
            calls.update(kwargs)

    monkeypatch.setattr(qdrant, "get_client", lambda: FakeClient())
    await qdrant.backfill_repo_user_payload("11111111-1111-1111-1111-111111111111", 9)

    assert calls["payload"] == {"user_id": 9}
    assert calls["collection_name"]


@pytest.mark.asyncio
async def test_purge_user_resources_cleans_vectors_storage_and_usage(monkeypatch):
    async def fake_query(_sql, _params):
        return [("repo-1",)]

    cleanup_repo = AsyncMock(return_value={
        "containers": 1, "workspaces": 1, "volumes": 2,
    })
    delete_points = AsyncMock()
    cleanup_storage = AsyncMock()
    execute = AsyncMock()

    monkeypatch.setattr(account_cleanup, "query", fake_query)
    monkeypatch.setattr(account_cleanup, "execute", execute)
    monkeypatch.setattr(account_cleanup, "cleanup_user_storage", cleanup_storage)
    monkeypatch.setattr("app.core.deploy.service.cleanup_repo_resources", cleanup_repo)
    monkeypatch.setattr("app.db.qdrant.delete_repo_points", delete_points)

    result = await account_cleanup.purge_user_resources(7)

    cleanup_repo.assert_awaited_once_with("repo-1", 7)
    delete_points.assert_awaited_once_with("repo-1")
    cleanup_storage.assert_awaited_once_with(7)
    assert result["containers"] == 1
    assert execute.await_count == 2

"""Cross-resource isolation helpers: ledger, Qdrant payload and account purge."""
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.core import account_cleanup
from app.core.deploy import ledger
from app.core.memory import session as session_mod
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


@pytest.mark.asyncio
async def test_cleanup_expired_guests_purges_then_deletes(monkeypatch):
    async def fake_query(_sql, _params):
        return [(5,), (6,)]

    purge = AsyncMock()
    execute = AsyncMock()
    monkeypatch.setattr(account_cleanup, "query", fake_query)
    monkeypatch.setattr(account_cleanup, "purge_user_resources", purge)
    monkeypatch.setattr(account_cleanup, "execute", execute)

    removed = await account_cleanup.cleanup_expired_guests()

    assert removed == 2
    assert purge.await_count == 2
    assert execute.await_count == 2


# ---------- SQL-level owner enforcement on message/trace reads ----------

SID = "11111111-1111-1111-1111-111111111111"


@pytest.mark.asyncio
async def test_get_messages_enforces_owner_in_sql(monkeypatch):
    query = AsyncMock(return_value=[])
    monkeypatch.setattr(session_mod, "query", query)

    await session_mod.get_messages(SID, user_id=2)
    sql, params = query.await_args.args
    assert "s.user_id = %s" in sql
    assert 2 in params

    # Without user_id the clause is absent (internal trusted callers only).
    query.reset_mock()
    await session_mod.get_messages(SID)
    sql, _params = query.await_args.args
    assert "s.user_id" not in sql


@pytest.mark.asyncio
async def test_recent_messages_and_messages_after_enforce_owner(monkeypatch):
    query = AsyncMock(return_value=[])
    monkeypatch.setattr(session_mod, "query", query)

    await session_mod.recent_messages(SID, user_id=3)
    sql, params = query.await_args.args
    assert "s.user_id = %s" in sql
    assert 3 in params

    query.reset_mock()
    await session_mod.messages_after(SID, 10, user_id=3)
    sql, params = query.await_args.args
    assert "s.user_id = %s" in sql
    assert 3 in params


@pytest.mark.asyncio
async def test_count_messages_since_enforces_owner(monkeypatch):
    query = AsyncMock(return_value=[(0,)])
    monkeypatch.setattr(session_mod, "query", query)

    await session_mod.count_messages_since(SID, 5, user_id=4)
    sql, params = query.await_args.args
    assert "s.user_id = %s" in sql
    assert 4 in params


@pytest.mark.asyncio
async def test_list_events_enforces_owner(monkeypatch):
    query = AsyncMock(return_value=[])
    # list_events imports query from app.db at call time.
    import app.db as db_mod
    monkeypatch.setattr(db_mod, "query", query)

    from app.core import trace as trace_refetch
    await trace_refetch.list_events(SID, user_id=5)
    sql, params = query.await_args.args
    assert "s.user_id = %s" in sql
    assert 5 in params


@pytest.mark.asyncio
async def test_wrong_owner_gets_404_on_messages_endpoint(monkeypatch):
    """API handler must 404 before any message row is read for a foreign session."""
    from app.api.v1 import chat as chat_api

    async def fake_get_session(session_id, user_id):
        return None if user_id == 2 else {"id": session_id, "title": "t"}

    get_messages = AsyncMock(return_value=[])
    monkeypatch.setattr(chat_api.session_mod, "get_session", fake_get_session)
    monkeypatch.setattr(chat_api.session_mod, "get_messages", get_messages)

    with pytest.raises(HTTPException) as exc:
        await chat_api.get_session_messages(SID, user={"id": 2})
    assert exc.value.status_code == 404
    get_messages.assert_not_awaited()


def test_qdrant_repo_filter_includes_user_id():
    flt = qdrant.repo_filter([SID], user_id=6)
    keys = [c.key for c in flt.must]
    assert keys == ["repo_id", "user_id"]

    flt_no_user = qdrant.repo_filter([SID])
    assert [c.key for c in flt_no_user.must] == ["repo_id"]

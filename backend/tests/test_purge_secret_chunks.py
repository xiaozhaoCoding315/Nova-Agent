"""Old-index cleanup script."""
from unittest.mock import AsyncMock

import pytest

from scripts import purge_secret_chunks as mod


@pytest.mark.asyncio
async def test_purge_dry_run_reports_without_deleting(monkeypatch):
    files = [
        (1, "r1", ".env"),
        (2, "r1", "main.py"),
        (3, "r1", "credentials.json"),
    ]

    async def fake_query(sql, params):
        if "repo_files" in sql:
            return files
        return [(11,), (12,)]

    delete = AsyncMock(return_value=2)
    monkeypatch.setattr(mod, "query", fake_query)
    monkeypatch.setattr(mod, "execute", AsyncMock())
    monkeypatch.setattr("app.db.qdrant.delete_point_ids", delete)

    summary = await mod.purge(dry_run=True)

    assert summary["secret_files"] == 2
    assert summary["chunks"] == 4
    assert summary["points"] == 0
    assert mod.execute.await_count == 0
    delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_purge_deletes_chunks_points_and_files(monkeypatch):
    files = [(1, "r1", ".env"), (2, "r1", "main.py")]

    async def fake_query(sql, params):
        if "repo_files" in sql:
            return files
        return [(11,), (12,)]

    monkeypatch.setattr(mod, "query", fake_query)
    monkeypatch.setattr(mod, "execute", AsyncMock())
    monkeypatch.setattr("app.db.qdrant.delete_point_ids", AsyncMock(return_value=2))

    summary = await mod.purge()

    assert summary["secret_files"] == 1
    assert summary["chunks"] == 2
    assert summary["points"] == 2
    assert mod.execute.await_count == 3

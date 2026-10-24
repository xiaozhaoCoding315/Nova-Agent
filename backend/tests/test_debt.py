"""Debt radar: metric computation, snapshot persistence and pruning."""
from unittest.mock import AsyncMock

import pytest

from app.core.debt import service as debt


@pytest.mark.asyncio
async def test_compute_metrics_is_bounded(monkeypatch):
    async def fake_query(sql, params):
        if "ILIKE 'tests/%'" in sql or "OR path ILIKE" in sql:
            return [(5,)]
        if "FROM repo_files WHERE repo_id = %s $" in sql or "SUM(line_count)" in sql:
            return [(20, 5000)]
        if "FROM chunks" in sql:
            return [(3,)]
        if "ORDER BY span DESC" in sql:
            return [("big_func", "function", 200)]
        if "(line_end - line_start) >" in sql:
            return [(4,)]
        if "FROM symbols WHERE repo_id" in sql:
            return [(40,)]
        if "ORDER BY line_count DESC" in sql:
            return [("app/huge.py", 1200)]
        return []

    monkeypatch.setattr(debt, "query", fake_query)
    metrics = await debt.compute_metrics("r1")
    assert metrics["file_count"] == 20
    assert metrics["test_file_count"] == 5
    assert metrics["long_function_count"] == 4
    assert 0 <= metrics["score"] <= 100
    assert metrics["long_functions"][0]["name"] == "big_func"
    assert metrics["huge_files"][0]["lines"] == 1200


@pytest.mark.asyncio
async def test_scan_repo_persists_and_prunes(monkeypatch):
    execute = AsyncMock()

    async def fake_query(sql, params):
        if "SELECT user_id FROM repos" in sql:
            return [(7,)]
        return []

    monkeypatch.setattr(debt, "query", fake_query)
    monkeypatch.setattr(debt, "execute", execute)
    metrics = await debt.scan_repo("r1")
    assert 0 <= metrics["score"] <= 100
    assert execute.await_count == 2          # insert snapshot + prune
    insert_sql = execute.await_args_list[0].args[0]
    assert "INSERT INTO debt_snapshots" in insert_sql
    prune_sql = execute.await_args_list[1].args[0]
    assert "DELETE FROM debt_snapshots" in prune_sql


@pytest.mark.asyncio
async def test_scan_stale_repos_bounds_work(monkeypatch):
    scanned = []

    async def fake_query(sql, params):
        if "SELECT r.id FROM repos" in sql:
            return [("r1",), ("r2",)]
        return []

    async def fake_scan(repo_id, user_id=None):
        scanned.append(repo_id)
        return {"score": 0}

    monkeypatch.setattr(debt, "query", fake_query)
    monkeypatch.setattr(debt, "scan_repo", fake_scan)
    assert await debt.scan_stale_repos(max_repos=2) == 2
    assert scanned == ["r1", "r2"]

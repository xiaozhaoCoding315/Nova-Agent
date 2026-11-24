"""Deterministic nightly consolidation of near-duplicate facts."""
from datetime import date
from unittest.mock import AsyncMock

import pytest

from app.core.memory import cleanup as cleanup_mod
from app.core.memory import facts as facts_mod


@pytest.mark.asyncio
async def test_consolidate_archives_near_duplicates_in_same_scope(monkeypatch):
    rows = [
        (1, 7, "dev", "", [1.0, 0.0], 1.2, None, None),
        (2, 7, "dev", "", [0.999, 0.001], 1.0, None, None),
        (3, 7, "dev", "", [0.0, 1.0], 1.0, None, None),
        (4, 8, "dev", "", [1.0, 0.0], 1.0, None, None),
    ]
    execute = AsyncMock()
    monkeypatch.setattr(facts_mod, "query", AsyncMock(return_value=rows))
    monkeypatch.setattr(facts_mod, "execute", execute)

    merged = await facts_mod.consolidate_duplicates()

    assert merged == 1
    sql, params = execute.await_args.args
    assert "status = 'archived'" in sql
    assert "merged_into_id" in sql
    assert params == (1, 2, 7)


@pytest.mark.asyncio
async def test_consolidate_keeps_distinct_scopes_separate(monkeypatch):
    rows = [
        (1, 7, "repo", "r1", [1.0, 0.0], 1.0, None, None),
        (2, 7, "repo", "r2", [1.0, 0.0], 1.0, None, None),
    ]
    execute = AsyncMock()
    monkeypatch.setattr(facts_mod, "query", AsyncMock(return_value=rows))
    monkeypatch.setattr(facts_mod, "execute", execute)

    assert await facts_mod.consolidate_duplicates() == 0
    execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_cleanup_runs_consolidation_once_per_day(monkeypatch):
    monkeypatch.setattr(cleanup_mod, "_last_consolidated", None)
    monkeypatch.setattr(
        cleanup_mod.facts, "run_cleanup", AsyncMock(side_effect=lambda: {}),
    )
    monkeypatch.setattr(cleanup_mod.facts, "promote_facts", AsyncMock(return_value=0))
    monkeypatch.setattr(
        cleanup_mod.facts, "consolidate_duplicates", AsyncMock(return_value=2),
    )
    monkeypatch.setattr(
        cleanup_mod.daily, "rollup_yesterday", AsyncMock(return_value=0),
    )

    first = await cleanup_mod.run_cleanup()
    second = await cleanup_mod.run_cleanup()

    assert first["facts_consolidated"] == 2
    assert "facts_consolidated" not in second
    assert cleanup_mod._last_consolidated == date.today()

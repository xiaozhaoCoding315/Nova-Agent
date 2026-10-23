"""Delivery metrics aggregation."""
from unittest.mock import AsyncMock

import pytest

from app.core.metrics import service as metrics_mod


@pytest.mark.asyncio
async def test_compute_metrics_aggregates_rates_and_costs(monkeypatch):
    query = AsyncMock(side_effect=[
        [(5, 3, 1)],
        [(10, 8, 2, 6)],
        [(2.5,)],
        [(1234,)],
        [(12.3,)],
    ])
    monkeypatch.setattr(metrics_mod, "query", query)

    result = await metrics_mod.compute_metrics(1, 7)

    assert result["accepted_changes"] == 3
    assert result["changes_total"] == 5
    assert result["tasks_total"] == 10
    assert result["first_gate_pass_rate"] == 0.75
    assert result["rework_rate"] == 0.2
    assert result["approval_minutes_avg"] == 2.5
    assert result["tokens_total"] == 1234
    assert result["p95_job_seconds"] == 12.3


def test_rate_handles_empty_denominator():
    assert metrics_mod._rate(0, 0) == 0.0
    assert metrics_mod._rate(1, 4) == 0.25

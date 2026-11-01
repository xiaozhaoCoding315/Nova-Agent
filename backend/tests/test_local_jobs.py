"""Local mode: one job worker, pruned maintenance, and index retry."""
import sys
import uuid
from unittest.mock import AsyncMock

import pytest

from app.config import settings
from app.core.indexing import retry
from app.core.jobs.runner import JobRunner
from app import main as main_module

# ``app.core.jobs.__init__`` re-exports the runner *instance* under the name
# ``runner``, which shadows the submodule attribute.  Tests must patch the real
# module (as ``tests/test_jobs.py`` does) so module-level names such as
# ``execute`` are replaced.
runner_module = sys.modules["app.core.jobs.runner"]


@pytest.mark.asyncio
async def test_claim_one_stops_at_local_single_worker(monkeypatch):
    monkeypatch.setattr(settings, "nova_mode", "local")
    runner = JobRunner()
    runner.register("demo", AsyncMock(return_value={}))
    runner._active = {"job-1": object()}
    called = False

    async def fake_execute(*args, **kwargs):
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(runner_module, "execute", fake_execute)
    assert await runner._claim_one() is None
    assert called is False


@pytest.mark.asyncio
async def test_claim_one_claims_in_server_mode_when_global_cap_disabled(monkeypatch):
    monkeypatch.setattr(settings, "nova_mode", "server")
    monkeypatch.setattr(settings, "job_max_concurrency", 0)
    runner = JobRunner()
    runner.register("demo", AsyncMock(return_value={}))
    runner._active = {"running-job": object()}
    job_id = str(uuid.uuid4())
    row = (job_id, 7, "demo", {"repo_id": "r1"}, 1, 1)

    async def fake_execute(*_args, **_kwargs):
        return [row]

    monkeypatch.setattr(runner_module, "execute", fake_execute)
    job = await runner._claim_one()
    assert job is not None
    assert job.id == job_id
    assert job.payload == {"repo_id": "r1"}


@pytest.mark.asyncio
async def test_claim_one_respects_server_global_cap(monkeypatch):
    monkeypatch.setattr(settings, "nova_mode", "server")
    monkeypatch.setattr(settings, "job_max_concurrency", 2)
    runner = JobRunner()
    runner.register("demo", AsyncMock(return_value={}))
    calls = 0

    async def fake_execute(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return [(str(uuid.uuid4()), 7, "demo", {}, 1, 1)]

    monkeypatch.setattr(runner_module, "execute", fake_execute)
    runner._active = {"job-1": object()}
    assert await runner._claim_one() is not None  # one of two slots free
    runner._active["job-2"] = object()
    assert await runner._claim_one() is None  # at the cap: no DB claim
    assert calls == 1


@pytest.mark.asyncio
async def test_retry_pending_indexes_enqueues_stale_repos(monkeypatch):
    monkeypatch.setattr(settings, "nova_mode", "local")
    enqueued: list[tuple] = []

    async def fake_query(sql, params):
        return [("repo-1", 1), ("repo-2", 2)]

    async def fake_enqueue(repo_id, **kwargs):
        enqueued.append((repo_id, kwargs))
        return "job"

    monkeypatch.setattr(retry, "query", fake_query)
    monkeypatch.setattr(retry, "enqueue_index", fake_enqueue)
    assert await retry.retry_pending_indexes(stale_seconds=60) == 2
    assert enqueued == [
        ("repo-1", {"user_id": 1}),
        ("repo-2", {"user_id": 2}),
    ]


@pytest.mark.asyncio
async def test_retry_pending_indexes_query_excludes_active_index_jobs(monkeypatch):
    monkeypatch.setattr(settings, "nova_mode", "local")
    captured: dict = {}
    enqueue = AsyncMock(return_value="job")

    async def fake_query(sql, params):
        captured["sql"] = " ".join(sql.split())
        captured["params"] = params
        return []

    monkeypatch.setattr(retry, "query", fake_query)
    monkeypatch.setattr(retry, "enqueue_index", enqueue)
    assert await retry.retry_pending_indexes() == 0
    enqueue.assert_not_awaited()

    sql = captured["sql"]
    assert captured["params"] == (600,)
    assert "r.status IN ('pending', 'indexing')" in sql
    assert "r.updated_at < now() - (%s * interval '1 second')" in sql
    assert "NOT EXISTS" in sql
    assert "j.kind = 'index'" in sql
    assert "j.status IN ('queued', 'running')" in sql
    assert "j.payload->>'repo_id' = r.id::text" in sql
    assert "ORDER BY r.updated_at" in sql
    assert "LIMIT 20" in sql


@pytest.mark.asyncio
async def test_retry_pending_indexes_stops_on_enqueue_error(monkeypatch):
    """The brief's loop has no per-row guard, so the error propagates."""
    monkeypatch.setattr(settings, "nova_mode", "local")
    attempted: list[str] = []

    async def fake_query(sql, params):
        return [("repo-1", 1), ("repo-2", 2)]

    async def fake_enqueue(repo_id, **kwargs):
        attempted.append(repo_id)
        raise RuntimeError("runner down")

    monkeypatch.setattr(retry, "query", fake_query)
    monkeypatch.setattr(retry, "enqueue_index", fake_enqueue)
    with pytest.raises(RuntimeError, match="runner down"):
        await retry.retry_pending_indexes()
    assert attempted == ["repo-1"]


@pytest.mark.asyncio
async def test_retry_pending_indexes_is_server_noop(monkeypatch):
    monkeypatch.setattr(settings, "nova_mode", "server")
    query = AsyncMock()
    monkeypatch.setattr(retry, "query", query)
    assert await retry.retry_pending_indexes() == 0
    query.assert_not_awaited()


@pytest.mark.asyncio
async def test_local_maintenance_skips_cloud_steps(monkeypatch):
    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr("app.core.memory.cleanup.run_cleanup", AsyncMock(return_value={"facts": 3}))
    monkeypatch.setattr(
        "app.core.indexing.retry.retry_pending_indexes", AsyncMock(return_value=2)
    )
    deploy = AsyncMock()
    guests = AsyncMock()
    debt = AsyncMock()
    lessons = AsyncMock()
    monkeypatch.setattr("app.core.deploy.service.cleanup_expired", deploy)
    monkeypatch.setattr("app.core.account_cleanup.cleanup_expired_guests", guests)
    monkeypatch.setattr("app.core.debt.service.scan_stale_repos", debt)
    monkeypatch.setattr("app.core.reflection.service.extract_lessons", lessons)

    summary = await main_module._maintenance_once()
    assert summary == {"facts": 3, "index_retried": 2}
    deploy.assert_not_awaited()
    guests.assert_not_awaited()
    debt.assert_not_awaited()
    lessons.assert_not_awaited()


@pytest.mark.asyncio
async def test_server_maintenance_runs_all_steps_and_isolates_failures(monkeypatch):
    monkeypatch.setattr(settings, "nova_mode", "server")
    calls: list[str] = []

    async def fake_cleanup():
        return {"facts": 1}

    async def failing_previews():
        calls.append("previews")
        raise RuntimeError("previews down")

    async def fake_guests():
        calls.append("guests")
        return 2

    async def fake_debt():
        calls.append("debt")
        return 3

    async def fake_lessons():
        calls.append("lessons")
        return 4

    monkeypatch.setattr("app.core.memory.cleanup.run_cleanup", fake_cleanup)
    monkeypatch.setattr("app.core.deploy.service.cleanup_expired", failing_previews)
    monkeypatch.setattr("app.core.account_cleanup.cleanup_expired_guests", fake_guests)
    monkeypatch.setattr("app.core.debt.service.scan_stale_repos", fake_debt)
    monkeypatch.setattr("app.core.reflection.service.extract_lessons", fake_lessons)
    monkeypatch.setattr(
        "app.core.indexing.retry.retry_pending_indexes",
        AsyncMock(side_effect=AssertionError("retry must not run on the server")),
    )

    summary = await main_module._maintenance_once()

    assert calls == ["previews", "guests", "debt", "lessons"]
    assert summary == {
        "facts": 1,
        "guests_expired": 2,
        "debt_scanned": 3,
        "lessons_extracted": 4,
    }

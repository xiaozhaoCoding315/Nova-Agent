"""Job runner basics: handler registration, enqueue persistence, retry."""
import asyncio
import sys
from unittest.mock import AsyncMock

import pytest

from app.api.v1 import jobs as jobs_api
from app.core.jobs.handlers import register_all
from app.core.jobs.runner import JobRunner

runner_module = sys.modules["app.core.jobs.runner"]


def test_builtin_handlers_include_summary_and_index():
    runner = JobRunner()
    register_all(runner)
    assert runner.has("index")
    assert runner.has("task")
    assert runner.has("builder_plan")
    assert runner.has("builder_files")
    assert runner.has("session_summary")
    assert runner.has("verify")


def test_jobs_router_exposes_lifecycle_endpoints():
    paths = {route.path for route in jobs_api.router.routes}
    assert "/jobs" in paths
    assert "/jobs/{job_id}" in paths
    assert "/jobs/{job_id}/cancel" in paths
    assert "/jobs/{job_id}/retry" in paths


@pytest.mark.asyncio
async def test_enqueue_persists_job(monkeypatch):
    runner = JobRunner()

    async def handler(ctx):
        return {}

    runner.register("demo", handler)
    execute = AsyncMock(return_value=[])
    monkeypatch.setattr(runner_module, "execute", execute)

    job_id = await runner.enqueue("demo", {"repo_id": "r1"}, user_id=3)

    assert isinstance(job_id, str) and len(job_id) == 36
    sql, params = execute.await_args.args
    assert "INSERT INTO jobs" in sql
    assert params[1] == 3
    assert params[2] == "demo"


@pytest.mark.asyncio
async def test_retry_requeues_only_failed_or_canceled(monkeypatch):
    runner = JobRunner()
    execute = AsyncMock(return_value=[("job-1",)])
    row = (
        "job-1", 3, "index", {}, "queued", 0, None, {}, None,
        0, 1, False, None, None, None,
    )
    query = AsyncMock(return_value=[row])
    monkeypatch.setattr(runner_module, "execute", execute)
    monkeypatch.setattr(runner_module, "query", query)

    job = await runner.retry("job-1", 3)

    sql, params = execute.await_args.args
    assert "status IN ('failed', 'canceled')" in sql
    assert "user_id = %s" in sql
    assert params == ("job-1", 3)
    assert job["status"] == "queued"


def test_chat_turn_is_registered_uncapped():
    runner = JobRunner()
    register_all(runner)

    assert runner.has("chat_turn")
    spec = runner._handlers["chat_turn"]  # noqa: SLF001
    assert spec.uncapped is True


@pytest.mark.asyncio
async def test_global_cap_still_allows_uncapped_kind(monkeypatch):
    runner = JobRunner()

    async def handler(ctx):
        return {}

    runner.register("index", handler)
    runner.register("chat_turn", handler, uncapped=True)
    runner._active_kinds = {"index": 1}  # noqa: SLF001
    monkeypatch.setattr(runner_module.settings, "job_max_concurrency", 1)
    monkeypatch.setattr(runner_module.settings, "nova_mode", "server")

    execute = AsyncMock(return_value=[])
    monkeypatch.setattr(runner_module, "execute", execute)

    claimed = await runner._claim_one()  # noqa: SLF001

    assert claimed is None
    _, params = execute.await_args.args
    assert params[0] == ["chat_turn"]


@pytest.mark.asyncio
async def test_shutdown_fails_chat_turn_instead_of_requeue(monkeypatch):
    runner = JobRunner()
    runner._running = True  # noqa: SLF001
    execute = AsyncMock(return_value=[])
    monkeypatch.setattr(runner_module, "execute", execute)
    monkeypatch.setattr(runner_module.logger, "info", lambda *a, **k: None)

    async def idle():
        await asyncio.sleep(30)

    task = asyncio.create_task(idle())
    runner._active = {"job-1": task}  # noqa: SLF001
    await runner.stop()

    sqls = [call.args[0] for call in execute.await_args_list]
    assert any(
        "kind = 'chat_turn'" in sql and "status = 'failed'" in sql for sql in sqls
    )
    assert any("kind <> 'chat_turn'" in sql for sql in sqls)


@pytest.mark.asyncio
async def test_recover_marks_chat_turn_failed(monkeypatch):
    runner = JobRunner()
    execute = AsyncMock(return_value=[])
    monkeypatch.setattr(runner_module, "execute", execute)

    await runner._recover_stale()  # noqa: SLF001

    first_sql = execute.await_args_list[0].args[0]
    assert "kind = 'chat_turn'" in first_sql
    assert "status = 'failed'" in first_sql
    assert execute.await_count == 2

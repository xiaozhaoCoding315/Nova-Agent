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
    assert runner.has("facts_extract")
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
async def test_enqueue_chat_turn_returns_none_when_runner_stopped():
    from app.core.jobs import service as jobs_service

    assert await jobs_service.enqueue_chat_turn("t-1", "s-1", 7) is None


@pytest.mark.asyncio
async def test_enqueue_facts_extract_is_durable_and_idempotent(monkeypatch):
    from types import SimpleNamespace

    from app.core.jobs import service as jobs_service

    fake_runner = SimpleNamespace(
        running=True, enqueue=AsyncMock(return_value="job-1"),
    )
    monkeypatch.setattr(jobs_service, "runner", fake_runner)

    job_id = await jobs_service.enqueue_facts_extract(
        "s1", 7, 11, 12, "thesis", "p1",
    )

    assert job_id == "job-1"
    assert fake_runner.enqueue.await_args.kwargs["idempotency_key"] == (
        "facts_extract:12"
    )
    assert fake_runner.enqueue.await_args.kwargs["max_attempts"] == 3


@pytest.mark.asyncio
async def test_enqueue_session_summary_keys_on_latest_message(monkeypatch):
    from types import SimpleNamespace

    from app.core.jobs import service as jobs_service

    fake_runner = SimpleNamespace(
        running=True, enqueue=AsyncMock(return_value="job-2"),
    )
    monkeypatch.setattr(jobs_service, "runner", fake_runner)
    monkeypatch.setattr(
        jobs_service, "query", AsyncMock(return_value=[(42,)])
    )

    assert await jobs_service.enqueue_session_summary("s1", 7) == "job-2"
    assert fake_runner.enqueue.await_args.kwargs["idempotency_key"] == (
        "session_summary:s1:42"
    )


@pytest.mark.asyncio
async def test_facts_extract_handler_reads_messages_and_scope(monkeypatch):
    from types import SimpleNamespace

    from app.core.jobs import handlers
    from app.core.memory import facts as facts_mod
    from app.core.memory import session as session_mod

    monkeypatch.setattr(
        session_mod, "get_session", AsyncMock(return_value={"id": "s1"})
    )
    monkeypatch.setattr(
        session_mod, "get_message",
        AsyncMock(side_effect=[
            {"id": 11, "role": "user", "content": "我在写论文"},
            {"id": 12, "role": "assistant", "content": "好的"},
        ]),
    )
    extract = AsyncMock(return_value=2)
    monkeypatch.setattr(facts_mod, "extract_facts_from_turn", extract)
    ctx = SimpleNamespace(
        payload={
            "session_id": "s1", "user_id": 7,
            "user_message_id": 11, "assistant_message_id": 12,
            "scope_type": "thesis", "scope_id": "p1",
        },
        check_cancel=AsyncMock(),
        update=AsyncMock(),
    )

    result = await handlers._facts_extract(ctx)

    assert result["facts_added"] == 2
    kwargs = extract.await_args.kwargs
    assert kwargs["scope_type"] == "thesis"
    assert kwargs["scope_id"] == "p1"
    assert kwargs["source_session_id"] == "s1"
    assert kwargs["source_message_id"] == 12
    assert kwargs["raise_on_error"] is True


@pytest.mark.asyncio
async def test_failed_job_requeues_with_exponential_backoff(monkeypatch):
    from app.core.jobs.models import Job

    runner = JobRunner()

    async def handler(_ctx):
        raise RuntimeError("utility model down")

    execute = AsyncMock(return_value=[])
    monkeypatch.setattr(runner_module, "execute", execute)
    job = Job(
        id="job-1", user_id=3, kind="facts_extract", payload={},
        attempts=1, max_attempts=3,
    )

    await runner._run(job, handler)  # noqa: SLF001

    sql, params = execute.await_args.args
    assert "available_at = now() + make_interval" in sql
    assert "POWER(2, attempts)" in sql
    assert params[1] == "job-1"


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
    assert spec.concurrency == 8


@pytest.mark.asyncio
async def test_global_cap_still_allows_uncapped_kind(monkeypatch):
    runner = JobRunner()

    async def handler(ctx):
        return {}

    runner.register("index", handler, concurrency=2)
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
async def test_uncapped_kind_still_bounded_by_own_concurrency(monkeypatch):
    runner = JobRunner()

    async def handler(ctx):
        return {}

    runner.register("index", handler, concurrency=2)
    runner.register("chat_turn", handler, concurrency=8, uncapped=True)
    runner._active_kinds = {"index": 1, "chat_turn": 8}  # noqa: SLF001
    monkeypatch.setattr(runner_module.settings, "job_max_concurrency", 1)
    monkeypatch.setattr(runner_module.settings, "nova_mode", "server")

    execute = AsyncMock(return_value=[])
    monkeypatch.setattr(runner_module, "execute", execute)

    assert await runner._claim_one() is None  # noqa: SLF001
    execute.assert_not_awaited()


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


@pytest.mark.asyncio
async def test_global_cap_ignores_uncapped_active_jobs(monkeypatch):
    runner = JobRunner()

    async def handler(ctx):
        return {}

    runner.register("index", handler, concurrency=2)
    runner.register("chat_turn", handler, concurrency=8, uncapped=True)
    runner._active_kinds = {"index": 1, "chat_turn": 1}  # noqa: SLF001
    monkeypatch.setattr(runner_module.settings, "job_max_concurrency", 2)
    monkeypatch.setattr(runner_module.settings, "nova_mode", "server")

    execute = AsyncMock(return_value=[])
    monkeypatch.setattr(runner_module, "execute", execute)

    assert await runner._claim_one() is None  # noqa: SLF001
    _, params = execute.await_args.args
    assert params[0] == ["index", "chat_turn"]


@pytest.mark.asyncio
async def test_cancel_running_chat_turn_bridges_to_turn_flag(monkeypatch):
    from app.core.sandbox import runtime as sandbox_runtime
    from app.core.turns import store as turn_store

    runner = JobRunner()
    execute = AsyncMock(return_value=[("running", "chat_turn", {"turn_id": "t-1"})])
    monkeypatch.setattr(runner_module, "execute", execute)
    monkeypatch.setattr(
        runner, "get", AsyncMock(return_value={"id": "j-1", "status": "running"}),
    )
    request_cancel = AsyncMock(return_value="running")
    monkeypatch.setattr(turn_store, "request_cancel", request_cancel)
    monkeypatch.setattr(
        sandbox_runtime, "kill_job_containers", AsyncMock(return_value=0),
    )

    job = await runner.cancel("j-1", 7)

    assert job["status"] == "running"
    request_cancel.assert_awaited_once_with("t-1")
    sql = execute.await_args.args[0]
    assert "RETURNING status, kind, payload" in sql
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_cancel_queued_chat_turn_still_marks_turn_canceled(monkeypatch):
    from app.core.turns import store as turn_store

    runner = JobRunner()
    execute = AsyncMock(return_value=[("canceled", "chat_turn", {"turn_id": "t-2"})])
    monkeypatch.setattr(runner_module, "execute", execute)
    monkeypatch.setattr(
        runner, "get", AsyncMock(return_value={"id": "j-2", "status": "canceled"}),
    )
    request_cancel = AsyncMock(return_value="canceled")
    monkeypatch.setattr(turn_store, "request_cancel", request_cancel)

    await runner.cancel("j-2", 7)

    request_cancel.assert_awaited_once_with("t-2")


@pytest.mark.asyncio
async def test_cancel_other_kind_does_not_touch_turns(monkeypatch):
    from app.core.sandbox import runtime as sandbox_runtime
    from app.core.turns import store as turn_store

    runner = JobRunner()
    execute = AsyncMock(return_value=[("running", "index", {})])
    monkeypatch.setattr(runner_module, "execute", execute)
    monkeypatch.setattr(
        runner, "get", AsyncMock(return_value={"id": "j-3", "status": "running"}),
    )
    request_cancel = AsyncMock()
    monkeypatch.setattr(turn_store, "request_cancel", request_cancel)
    monkeypatch.setattr(
        sandbox_runtime, "kill_job_containers", AsyncMock(return_value=0),
    )

    await runner.cancel("j-3", 7)

    request_cancel.assert_not_awaited()
    await asyncio.sleep(0)

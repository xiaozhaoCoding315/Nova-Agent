"""Night queue: validation, window, budget gate and dispatch."""
from unittest.mock import AsyncMock

import pytest

from app.config import settings
from app.core.night import service as night


@pytest.mark.asyncio
async def test_enqueue_requires_valid_kind_and_change(monkeypatch):
    with pytest.raises(ValueError):
        await night.enqueue_item(1, "bogus", change_id="x")

    async def fake_query(sql, params):
        if "change_requests" in sql:
            return [("t", "draft")]  # not plan_approved
        return []

    monkeypatch.setattr(night, "query", fake_query)
    with pytest.raises(ValueError):
        await night.enqueue_item(1, "change_execute", change_id="c1")

    async def fake_execute(sql, params):
        return None

    async def query_ok(sql, params):
        if "change_requests" in sql:
            return [("标题", "plan_approved")]
        return []

    monkeypatch.setattr(night, "query", query_ok)
    monkeypatch.setattr(night, "execute", fake_execute)
    item = await night.enqueue_item(1, "change_execute", change_id="c1")
    assert item["status"] == "pending"
    assert item["title"] == "标题"


def test_window_boundaries():
    import datetime as dt
    monkey = pytest.MonkeyPatch()
    monkey.setattr(settings, "night_window_start", 0)
    monkey.setattr(settings, "night_window_end", 8)
    try:
        assert night._in_window(dt.datetime(2026, 10, 24, 0, 30)) is True
        assert night._in_window(dt.datetime(2026, 10, 24, 7, 59)) is True
        assert night._in_window(dt.datetime(2026, 10, 24, 8, 0)) is False
        assert night._in_window(dt.datetime(2026, 10, 24, 12, 0)) is False
    finally:
        monkey.undo()


@pytest.mark.asyncio
async def test_budget_exhausted_respects_threshold(monkeypatch):
    async def fake_query(sql, params):
        return [("demo", False, None, None)]

    async def fake_tokens(user_id):
        return 95

    monkeypatch.setattr(night, "query", fake_query)
    monkeypatch.setattr(night, "tokens_used_today", fake_tokens)
    monkeypatch.setattr(night.settings, "demo_daily_tokens", 100)
    monkeypatch.setattr(night.settings, "night_budget_reserve", 0.2)
    # 95 >= 100 * 0.8 → stop dispatching
    assert await night._budget_exhausted(1) is True

    async def fake_tokens_low(user_id):
        return 50

    monkeypatch.setattr(night, "tokens_used_today", fake_tokens_low)
    assert await night._budget_exhausted(1) is False


@pytest.mark.asyncio
async def test_run_maintenance_skips_outside_window(monkeypatch):
    monkeypatch.setattr(night, "_in_window", lambda now=None: False)
    result = await night.run_maintenance()
    assert result == {"dispatched": 0, "skipped": "outside_window"}


@pytest.mark.asyncio
async def test_dispatch_marks_budget_failure(monkeypatch):
    executed = []

    async def fake_query(sql, params):
        if "FROM night_queue" in sql and "SELECT id, user_id, kind" in sql:
            return [("item-1", 1, "change_execute", {"change_id": "c1"})]
        return []

    async def fake_execute(sql, params):
        executed.append(sql)

    monkeypatch.setattr(night, "query", fake_query)
    monkeypatch.setattr(night, "execute", fake_execute)
    monkeypatch.setattr(night, "_budget_exhausted", AsyncMock(return_value=True))

    dispatched = await night._dispatch_pending()
    assert dispatched == 0
    assert any("预算" in sql for sql in executed)


@pytest.mark.asyncio
async def test_enqueue_chat_and_builder_kinds(monkeypatch):
    async def fake_query(sql, params):
        if "FROM sessions" in sql:
            return [(1,)]
        return []

    async def fake_execute(sql, params=None):
        return None

    monkeypatch.setattr(night, "query", fake_query)
    monkeypatch.setattr(night, "execute", fake_execute)

    chat = await night.enqueue_item(
        1, "chat", content="分析鉴权链路并给出风险清单", session_id="s1",
    )
    assert chat["status"] == "pending"
    assert chat["title"].startswith("分析鉴权链路")

    with pytest.raises(ValueError):
        await night.enqueue_item(1, "chat", content="")

    proj = await night.enqueue_item(
        1, "builder", name="blog-api", requirements="一个博客 API", stack="fullstack",
    )
    assert proj["title"] == "生成项目：blog-api"

    with pytest.raises(ValueError):
        await night.enqueue_item(1, "builder", name="x", requirements="y", stack="bogus")


@pytest.mark.asyncio
async def test_reconcile_builder_stage_chain(monkeypatch):
    """Plan-job success must approve the plan and enqueue the files job."""

    async def fake_query(sql, params=None):
        if "FROM night_queue" in sql and "kind" in sql:
            return [("item-1", 1, "job-plan", "builder",
                     {"repo_id": "r1", "stage": "plan"})]
        return []

    execute_calls = []

    async def fake_execute(sql, params=None):
        execute_calls.append((sql, params))

    async def fake_get(job_id, user_id=None):
        return {"status": "succeeded"}

    async def fake_approve(repo_id):
        return None

    async def fake_enqueue_files(repo_id, user_id):
        return "job-files"

    class FakeRunner:
        async def get(self, job_id, user_id=None):
            return await fake_get(job_id, user_id)

    import sys
    import app.core.jobs.service as jobs_service
    import app.core.builder.engine as engine_mod
    runner_mod = sys.modules["app.core.jobs.runner"]
    monkeypatch.setattr(night, "query", fake_query)
    monkeypatch.setattr(night, "execute", fake_execute)
    monkeypatch.setattr(engine_mod, "approve_plan", fake_approve)
    monkeypatch.setattr(jobs_service, "enqueue_builder_files", fake_enqueue_files)
    monkeypatch.setattr(runner_mod, "runner", FakeRunner())

    await night._reconcile_running()
    update = next(sql for sql, _ in execute_calls if "UPDATE night_queue" in sql)
    assert "job_id" in update
    params = next(p for sql, p in execute_calls if "UPDATE night_queue" in sql and p)
    assert "job-files" in params

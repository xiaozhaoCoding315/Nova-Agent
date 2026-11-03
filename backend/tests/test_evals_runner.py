"""Runner results, failure classification, and report rendering."""
import asyncio
import json

import pytest

from evals.checks import final_text_contains, tool_succeeded
from evals.models import CheckFailure, EvalTask, SuiteReport, TaskResult
from evals.report import (
    compare_baseline,
    load_baseline,
    render_markdown,
    render_summary,
    report_to_dict,
    write_baseline,
    write_json,
    write_markdown,
)
from evals.runner import run_suite, run_task


def _task(checks=(), script=None, timeout_s=60.0, fixture="python_small"):
    return EvalTask(
        id="runner_task",
        mode="scripted",
        category="test",
        description="runner test",
        prompt="读取 calc.py 并说明 add 返回什么。",
        fixture=fixture,
        checks=checks,
        script=script or (
            (
                {"type": "tool_calls", "tool_calls": [{
                    "id": "call-1", "name": "read_file",
                    "arguments": '{"path": "calc.py"}',
                }]},
                {"type": "finish", "finish_reason": "tool_calls"},
            ),
            (
                {"type": "content", "content": "add 返回 a - b。"},
                {"type": "finish", "finish_reason": "stop"},
            ),
        ),
        timeout_s=timeout_s,
    )


@pytest.mark.asyncio
async def test_run_task_passes_and_cleans_up():
    task = _task(checks=(final_text_contains("a - b"), tool_succeeded("read_file")))
    result = await run_task(task)
    assert result.status == "passed"
    assert result.tool_calls == 1
    assert result.rounds == 2
    assert [check["ok"] for check in result.checks] == [True, True]


@pytest.mark.asyncio
async def test_run_task_marks_check_failure_as_failed():
    task = _task(checks=(final_text_contains("a + b"),))
    result = await run_task(task)
    assert result.status == "failed"
    assert result.failure["check"].startswith("final_text_contains")
    assert "a + b" in result.failure["message"]


@pytest.mark.asyncio
async def test_run_task_marks_script_exhaustion_as_error():
    task = _task(script=(
        (
            {"type": "tool_calls", "tool_calls": [{
                "id": "call-1", "name": "read_file",
                "arguments": '{"path": "calc.py"}',
            }]},
            {"type": "finish", "finish_reason": "tool_calls"},
        ),
    ))
    result = await run_task(task)
    assert result.status == "error"
    assert "ScriptExhausted" in (result.error or "")


@pytest.mark.asyncio
async def test_run_task_marks_unknown_fixture_as_error():
    task = _task(fixture="missing")
    result = await run_task(task)
    assert result.status == "error"
    assert "未知 fixture" in (result.error or "")


@pytest.mark.asyncio
async def test_run_task_removes_the_fixture_directory(monkeypatch):
    from evals import runner as runner_mod

    roots = []
    real = runner_mod.create_fixture

    def _record(name):
        repo = real(name)
        roots.append(repo.root)
        return repo

    monkeypatch.setattr(runner_mod, "create_fixture", _record)
    result = await run_task(_task())
    assert result.status == "passed"
    assert roots and not roots[0].exists()


class _BlockingExecutor:
    """Yields one content event, then never finishes on its own."""

    def __init__(self, _rounds, *, context_window=131_072, supports_vision=False):
        self.context_window = context_window
        self.supports_vision = supports_vision
        self.llm_messages = []

    async def astream_with_tools(self, messages, _tools):
        self.llm_messages.append(messages)
        yield {"type": "content", "content": "partial answer"}
        await asyncio.Event().wait()


def _capture_fixtures(monkeypatch):
    from evals import runner as runner_mod

    repos = []
    real = runner_mod.create_fixture

    def _record(name):
        repo = real(name)
        repos.append(repo)
        return repo

    monkeypatch.setattr(runner_mod, "create_fixture", _record)
    return repos


@pytest.mark.asyncio
async def test_run_task_timeout_returns_error_and_removes_the_fixture(monkeypatch):
    from evals import runner as runner_mod

    repos = _capture_fixtures(monkeypatch)
    monkeypatch.setattr(runner_mod, "ScriptedExecutor", _BlockingExecutor)

    result = await asyncio.wait_for(run_task(_task(timeout_s=0.5)), timeout=15)

    assert result.status == "error"
    assert "任务超时" in (result.error or "")
    assert repos and not repos[0].root.exists()


@pytest.mark.asyncio
async def test_run_suite_skips_live_tasks_without_a_provider(monkeypatch):
    from evals import runner as runner_mod
    from evals.executors import EvalConfigError

    def _raise(_provider="auto", _model=None):
        raise EvalConfigError("没有可用模型")

    monkeypatch.setattr(runner_mod, "build_live_llm", _raise)

    live_task = EvalTask(
        id="live_task", mode="live", category="test", description="live",
        prompt="hi", fixture="python_small", checks=(),
    )
    scripted_task = EvalTask(
        id="scripted_would_error", mode="scripted", category="test",
        description="must not run", prompt="hi", fixture="python_small",
        checks=(), script=(),
    )

    report = await run_suite([live_task, scripted_task], "live")

    assert len(report.tasks) == 1
    result = report.tasks[0]
    assert result.task_id == "live_task"
    assert result.status == "skipped"
    assert "没有可用模型" in (result.error or "")
    assert report.provider is None


@pytest.mark.asyncio
async def test_run_task_marks_check_exception_as_error():
    def boom_check(_run):
        raise ValueError("boom")

    result = await run_task(_task(checks=(boom_check,)))

    assert result.status == "error"
    assert (result.error or "").startswith("检查器异常")
    assert result.checks[0]["ok"] is False


@pytest.mark.asyncio
async def test_run_task_redacts_secrets_in_check_failures():
    secret = "sk-" + "a" * 24

    def leak_check(_run):
        raise CheckFailure(f"leaked {secret}")

    result = await run_task(_task(checks=(leak_check,)))

    assert result.status == "failed"
    message = result.failure["message"]
    assert "[REDACTED]" in message
    assert secret not in message


@pytest.mark.asyncio
async def test_run_task_keep_retains_the_fixture(monkeypatch):
    repos = _capture_fixtures(monkeypatch)
    try:
        result = await run_task(_task(), keep=True)
        assert result.status == "passed"
        assert repos and repos[0].root.exists()
    finally:
        for repo in repos:
            repo.cleanup()


def _report(tmp_path):
    task = TaskResult(
        task_id="read_and_answer", mode="scripted", category="read",
        status="passed", duration_ms=12, rounds=2, tool_calls=1,
        checks=[{"name": "final_text_contains", "ok": True, "message": None}],
    )
    failed = TaskResult(
        task_id="edit_file_minimal", mode="scripted", category="edit",
        status="failed", duration_ms=8, rounds=2, tool_calls=1,
        checks=[{"name": "file_contains", "ok": False, "message": "missing"}],
        failure={"check": "file_contains", "message": "missing", "events_tail": []},
    )
    return SuiteReport(
        suite="smoke", mode="scripted", git_sha="abc1234", git_dirty=False,
        started_at="2026-11-03T00:00:00+00:00",
        finished_at="2026-11-03T00:00:01+00:00",
        duration_ms=20, provider=None, model=None, tasks=[task, failed],
    )


def test_report_to_dict_and_files(tmp_path):
    report = _report(tmp_path)
    data = report_to_dict(report)
    assert data["summary"]["passed"] == 1
    assert data["summary"]["failed"] == 1
    assert data["summary"]["pass_rate"] == 0.5

    json_path = tmp_path / "r.json"
    md_path = tmp_path / "r.md"
    write_json(report, json_path)
    write_markdown(report, md_path)
    assert json.loads(json_path.read_text(encoding="utf-8"))["tasks"][0]["task_id"] == "read_and_answer"
    assert "# Nova Agent Eval — scripted" in md_path.read_text(encoding="utf-8")
    assert render_markdown(report) == md_path.read_text(encoding="utf-8")
    assert "edit_file_minimal" in render_summary(report)


def test_load_baseline_accepts_an_old_report(tmp_path):
    report = _report(tmp_path)
    path = tmp_path / "old-report.json"
    write_json(report, path)
    baseline = load_baseline(path)
    assert baseline["tasks"] == {
        "read_and_answer": "passed",
        "edit_file_minimal": "failed",
    }


def test_compare_baseline_reports_regressions_improvements_and_missing():
    report = _report(None)
    baseline = {
        "tasks": {
            "read_and_answer": "failed",
            "edit_file_minimal": "passed",
            "removed_task": "passed",
        },
        "summary": {"pass_rate": 1.0},
    }
    diff = compare_baseline(report, baseline)
    assert diff["regressions"] == ["edit_file_minimal"]
    assert diff["improvements"] == ["read_and_answer"]
    assert diff["missing"] == ["removed_task"]
    assert diff["pass_rate_delta"] == -0.5


def test_render_summary_excludes_skipped_from_fraction():
    report = _report(None)
    report.tasks.append(TaskResult(
        task_id="live_x", mode="live", category="read", status="skipped",
    ))
    text = render_summary(report)
    assert "Pass rate: 1/2 (50.0%)" in text
    assert "skipped 1" in text


def test_empty_result_truncates_long_errors():
    from evals.runner import _empty_result
    from evals.tasks.smoke import READ_AND_ANSWER

    result = _empty_result(READ_AND_ANSWER, "error", "x" * 5000)
    assert result.error is not None
    assert len(result.error) <= 1000


def test_write_baseline_uses_task_statuses(tmp_path):
    report = _report(tmp_path)
    path = tmp_path / "baseline.json"
    write_baseline(report, path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["tasks"] == {
        "read_and_answer": "passed",
        "edit_file_minimal": "failed",
    }
    assert data["summary"]["pass_rate"] == 0.5

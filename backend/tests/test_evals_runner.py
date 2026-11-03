"""Runner results, failure classification, and report rendering."""
import json

import pytest

from evals.checks import final_text_contains, tool_succeeded
from evals.models import EvalTask, SuiteReport, TaskResult
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
from evals.runner import run_task


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

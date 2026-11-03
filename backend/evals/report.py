"""JSON and Markdown reports plus baseline comparison."""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from evals.models import SuiteReport


def report_to_dict(report: SuiteReport) -> dict:
    return {
        "suite": report.suite,
        "mode": report.mode,
        "git_sha": report.git_sha,
        "git_dirty": report.git_dirty,
        "started_at": report.started_at,
        "finished_at": report.finished_at,
        "duration_ms": report.duration_ms,
        "provider": report.provider,
        "model": report.model,
        "summary": report.summary,
        "tasks": [asdict(task) for task in report.tasks],
        "baseline": report.baseline,
    }


def write_json(report: SuiteReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report_to_dict(report), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _cell(value) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _task_row(task) -> str:
    return (
        f"| {_cell(task.task_id)} | {task.status} | {task.duration_ms}ms "
        f"| {task.rounds} | {task.tool_calls} | {task.prompt_tokens} "
        f"| {task.completion_tokens} |"
    )


def render_markdown(report: SuiteReport) -> str:
    summary = report.summary
    lines = [
        f"# Nova Agent Eval — {report.mode}",
        "",
        f"- Git: {report.git_sha} (dirty: {'yes' if report.git_dirty else 'no'})",
        f"- Started: {report.started_at}",
        f"- Duration: {report.duration_ms / 1000:.1f}s",
        (
            f"- Pass rate: {summary['passed']}/{summary['total']} "
            f"({summary['pass_rate'] * 100:.1f}%)"
        ),
    ]
    if report.provider:
        lines.append(f"- Provider: {report.provider} / {report.model}")
    lines.extend([
        "",
        "| Task | Status | Duration | Rounds | Tools | Prompt | Completion |",
        "|---|---|---|---|---|---|---|",
        *[_task_row(task) for task in report.tasks],
    ])

    failures = [
        task for task in report.tasks
        if task.status in ("failed", "error")
    ]
    if failures:
        lines.extend(["", "## Failures", ""])
        for task in failures:
            lines.append(f"### {task.task_id} — {task.status}")
            if task.failure:
                lines.append(f"- Check: `{task.failure.get('check')}`")
                lines.append(f"- Message: {task.failure.get('message')}")
                tail = task.failure.get("events_tail") or []
                if tail:
                    lines.append(f"- Last events: `{tail}`")
            if task.error:
                lines.append(f"- Error: {task.error}")
            lines.append("")

    if report.baseline:
        lines.extend([
            "## Baseline",
            "",
            f"- Regressions: {report.baseline.get('regressions')}",
            f"- Improvements: {report.baseline.get('improvements')}",
            f"- Missing: {report.baseline.get('missing')}",
            f"- Pass-rate delta: {report.baseline.get('pass_rate_delta')}",
            "",
        ])
    return "\n".join(lines)


def write_markdown(report: SuiteReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown(report), encoding="utf-8")


def render_summary(report: SuiteReport) -> str:
    summary = report.summary
    lines = [
        f"Nova Agent Eval — {report.mode}",
        (
            f"Git: {report.git_sha}"
            f"{' (dirty)' if report.git_dirty else ''}"
        ),
        (
            f"Pass rate: {summary['passed']}/{summary['total']} "
            f"({summary['pass_rate'] * 100:.1f}%)  "
            f"Duration: {report.duration_ms / 1000:.1f}s"
        ),
    ]
    for task in report.tasks:
        detail = ""
        if task.status == "failed" and task.failure:
            detail = f" — {task.failure.get('check')}: {task.failure.get('message')}"
        elif task.status == "error" and task.error:
            detail = f" — {task.error}"
        lines.append(f"  {task.status.upper():7} {task.task_id}{detail}")
    return "\n".join(lines)


def load_baseline(path: Path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    tasks = data.get("tasks")
    if isinstance(tasks, dict):
        return data
    if isinstance(tasks, list):
        data["tasks"] = {
            str(item["task_id"]): str(item["status"])
            for item in tasks
            if isinstance(item, dict) and item.get("task_id")
        }
        return data
    raise ValueError("基线文件缺少 tasks 对象或数组")


def compare_baseline(report: SuiteReport, baseline: dict) -> dict:
    old = {str(key): str(value) for key, value in (baseline.get("tasks") or {}).items()}
    current = {task.task_id: task.status for task in report.tasks}
    regressions = sorted(
        task_id for task_id, status in old.items()
        if status == "passed" and task_id in current
        and current[task_id] != "passed"
    )
    improvements = sorted(
        task_id for task_id, status in old.items()
        if status != "passed" and current.get(task_id) == "passed"
    )
    missing = sorted(task_id for task_id in old if task_id not in current)
    old_rate = float((baseline.get("summary") or {}).get("pass_rate") or 0.0)
    return {
        "regressions": regressions,
        "improvements": improvements,
        "missing": missing,
        "pass_rate_delta": round(report.summary["pass_rate"] - old_rate, 4),
    }


def write_baseline(report: SuiteReport, path: Path) -> None:
    data = {
        "suite": report.suite,
        "mode": report.mode,
        "generated_at": datetime.now(UTC).isoformat(),
        "git_sha": report.git_sha,
        "tasks": {task.task_id: task.status for task in report.tasks},
        "summary": {"pass_rate": report.summary["pass_rate"]},
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8",
    )

"""Task and suite orchestration."""
from __future__ import annotations

import asyncio
import json
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

from app.core.security.redaction import redact_text
from evals.checks import CheckFailure
from evals.executors import (
    EvalConfigError,
    LiveConfig,
    LiveExecutor,
    ScriptedExecutor,
    build_live_llm,
    close_live_llm,
)
from evals.fixtures import create_fixture
from evals.harness import InProcessHarness
from evals.models import EvalMode, EvalRun, EvalTask, SuiteReport, TaskResult

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_MAX_ERROR_CHARS = 1000


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _clip_error(text) -> str:
    return redact_text(str(text))[:_MAX_ERROR_CHARS]


def git_state() -> tuple[str, bool]:
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=PROJECT_ROOT, capture_output=True, text=True, check=False,
        )
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=PROJECT_ROOT, capture_output=True, text=True, check=False,
        )
        return sha.stdout.strip() or "unknown", bool(status.stdout.strip())
    except OSError:
        return "unknown", False


def _events_tail(run: EvalRun) -> list[dict]:
    tail = []
    for event in run.events[-5:]:
        data = json.dumps(event.get("data"), ensure_ascii=False, default=str)
        tail.append({"event": event.get("event"), "data": redact_text(data)[:500]})
    return tail


def _result(
    run: EvalRun,
    status: str,
    checks: list[dict],
    *,
    failure: dict | None = None,
    error: str | None = None,
) -> TaskResult:
    return TaskResult(
        task_id=run.task.id,
        mode=run.task.mode,
        category=run.task.category,
        status=status,
        duration_ms=run.duration_ms,
        rounds=run.rounds,
        tool_calls=len(run.tool_calls),
        prompt_tokens=int(run.usage.get("prompt_tokens") or 0),
        completion_tokens=int(run.usage.get("completion_tokens") or 0),
        checks=checks,
        failure=failure,
        error=_clip_error(error) if error else None,
    )


def _empty_result(task: EvalTask, status: str, error: str) -> TaskResult:
    return TaskResult(
        task_id=task.id,
        mode=task.mode,
        category=task.category,
        status=status,
        error=_clip_error(error),
    )


async def run_task(
    task: EvalTask,
    *,
    live_config: LiveConfig | None = None,
    keep: bool = False,
) -> TaskResult:
    try:
        repo = create_fixture(task.fixture)
    except Exception as exc:  # noqa: BLE001
        return _empty_result(task, "error", f"fixture 创建失败：{exc}")

    try:
        if task.mode == "scripted":
            executor = ScriptedExecutor(
                task.script or (),
                context_window=task.context_window or 131_072,
                supports_vision=any(
                    item.get("mime") == "image/png" for item in task.attachments
                ),
            )
        else:
            if live_config is None:
                return _empty_result(task, "skipped", "live provider 未配置")
            executor = LiveExecutor(live_config.llm)

        with InProcessHarness(task, repo, executor) as harness:
            try:
                run = await asyncio.wait_for(harness.run(), timeout=task.timeout_s)
            except TimeoutError:
                return _empty_result(
                    task, "error", f"任务超时（{task.timeout_s:g}s）",
                )

        if run.error:
            return _result(run, "error", [], error=run.error)

        checks: list[dict] = []
        for check in task.checks:
            name = getattr(check, "__name__", "check")
            try:
                check(run)
            except CheckFailure as exc:
                message = _clip_error(str(exc))
                checks.append({"name": name, "ok": False, "message": message})
                return _result(run, "failed", checks, failure={
                    "check": name,
                    "message": message,
                    "events_tail": _events_tail(run),
                })
            except Exception as exc:  # noqa: BLE001
                message = _clip_error(f"{type(exc).__name__}: {exc}")
                checks.append({"name": name, "ok": False, "message": message})
                return _result(run, "error", checks, error=f"检查器异常：{message}")
            checks.append({"name": name, "ok": True, "message": None})

        return _result(run, "passed", checks)
    except Exception as exc:  # noqa: BLE001
        return _empty_result(
            task,
            "error",
            f"{type(exc).__name__}: {exc}",
        )
    finally:
        if not keep:
            repo.cleanup()


async def run_suite(
    tasks: list[EvalTask],
    mode: EvalMode,
    *,
    provider: str = "auto",
    model: str | None = None,
    keep: bool = False,
) -> SuiteReport:
    started_at = _now()
    started = time.perf_counter()
    live_config: LiveConfig | None = None
    live_error: str | None = None
    if mode == "live":
        try:
            live_config = build_live_llm(provider, model)
        except EvalConfigError as exc:
            live_error = str(exc)

    results: list[TaskResult] = []
    try:
        for task in tasks:
            if task.mode != mode:
                continue
            if mode == "live" and live_config is None:
                results.append(_empty_result(
                    task, "skipped", live_error or "live provider 未配置",
                ))
                continue
            results.append(await run_task(
                task, live_config=live_config, keep=keep,
            ))
    finally:
        if live_config is not None:
            await close_live_llm(live_config.llm)

    finished_at = _now()
    sha, dirty = git_state()
    return SuiteReport(
        suite="smoke",
        mode=mode,
        git_sha=sha,
        git_dirty=dirty,
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=int((time.perf_counter() - started) * 1000),
        provider=live_config.provider if live_config else None,
        model=live_config.model if live_config else None,
        tasks=results,
    )

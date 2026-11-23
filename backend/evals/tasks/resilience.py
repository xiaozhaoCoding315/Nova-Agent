"""Fault-injection evals: retry, classification, and no-replay guarantees.

These tasks script *failures*, not answers.  They exist because the retry
rules are the easiest part of the harness to break silently: a change that
retries an invalid API key, or that gives up on a transient 503, passes every
happy-path test.
"""
from __future__ import annotations

from evals.checks import (
    expect,
    final_text_contains,
    llm_saw_plan_block,
    no_notice,
    notice_seen,
)
from evals.executors import ScriptedFailure
from evals.models import Check, EvalRun, EvalTask


class ProviderStatusError(Exception):
    """Stand-in for openai.APIStatusError: only status_code matters here."""

    def __init__(self, status_code: int, message: str = ""):
        super().__init__(message or f"status {status_code}")
        self.status_code = status_code


def _answer(text: str) -> tuple[dict, ...]:
    return (
        {"type": "content", "content": text},
        {"type": "finish", "finish_reason": "stop"},
    )


def llm_called_times(count: int) -> Check:
    def check(run: EvalRun) -> None:
        expect(
            len(run.llm_messages) == count,
            f"模型被调用 {len(run.llm_messages)} 次，期望 {count} 次",
        )

    check.__name__ = f"llm_called_times({count})"
    return check


def error_event(code: str) -> Check:
    def check(run: EvalRun) -> None:
        codes = [
            (event.get("data") or {}).get("code")
            for event in run.events if event.get("event") == "error"
        ]
        expect(code in codes, f"没有 error code={code}；实际：{codes}")

    check.__name__ = f"error_event({code})"
    return check


def no_error_event() -> Check:
    def check(run: EvalRun) -> None:
        errors = [event for event in run.events if event.get("event") == "error"]
        expect(not errors, f"出现 error 事件：{[e.get('data') for e in errors]}")

    check.__name__ = "no_error_event"
    return check


TRANSIENT_503_IS_RETRIED = EvalTask(
    id="transient_503_is_retried",
    mode="scripted",
    category="resilience",
    description="瞬时 503 退避后重试成功，不向用户报错",
    prompt="你好，介绍一下你自己。",
    fixture="empty",
    checks=(
        notice_seen("retry"),
        no_error_event(),
        llm_called_times(2),
        final_text_contains("恢复"),
    ),
    script=(
        ScriptedFailure(ProviderStatusError(503, "upstream unavailable")),
        _answer("服务已恢复，我在。"),
    ),
)

DETERMINISTIC_401_IS_NOT_RETRIED = EvalTask(
    id="deterministic_401_is_not_retried",
    mode="scripted",
    category="resilience",
    description="鉴权失败不重试、不续跑，直接报错",
    prompt="你好。",
    fixture="empty",
    expect_error=True,
    checks=(
        error_event("llm_error"),
        no_notice("retry"),
        no_notice("continued"),
        llm_called_times(1),
    ),
    script=(
        ScriptedFailure(ProviderStatusError(401, "invalid api key")),
    ),
)

EXHAUSTED_QUOTA_IS_NOT_RETRIED = EvalTask(
    id="exhausted_quota_is_not_retried",
    mode="scripted",
    category="resilience",
    description="额度耗尽（429 + insufficient_quota）视为确定性失败",
    prompt="你好。",
    fixture="empty",
    expect_error=True,
    checks=(
        error_event("llm_error"),
        no_notice("retry"),
        llm_called_times(1),
    ),
    script=(
        ScriptedFailure(ProviderStatusError(
            429, "insufficient_quota: you exceeded your current quota",
        )),
    ),
)

PLAN_SURVIVES_A_CONTINUATION = EvalTask(
    id="plan_survives_a_continuation",
    mode="scripted",
    category="resilience",
    description="上一段建立的计划在续跑时重新进入 system prompt",
    prompt="继续完成任务。",
    fixture="python_small",
    prior_plan={
        "steps": [
            {"title": "读取 calc.py", "status": "completed"},
            {"title": "修复 add", "status": "in_progress"},
        ],
        "explanation": "先读后改",
    },
    checks=(
        llm_saw_plan_block(),
        final_text_contains("按计划"),
    ),
    script=(
        _answer("按计划继续：下一步修复 add。"),
    ),
)

ALL_TASKS = (
    TRANSIENT_503_IS_RETRIED,
    DETERMINISTIC_401_IS_NOT_RETRIED,
    EXHAUSTED_QUOTA_IS_NOT_RETRIED,
    PLAN_SURVIVES_A_CONTINUATION,
)

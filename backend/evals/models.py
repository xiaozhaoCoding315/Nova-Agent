"""Data models shared by the eval harness."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from evals.fixtures import FixtureRepo

EvalMode = Literal["scripted", "live"]
TaskStatus = Literal["passed", "failed", "error", "skipped"]


class CheckFailure(AssertionError):
    """Raised by a check when the eval result does not meet the expectation."""


Check = Callable[["EvalRun"], None]


@dataclass(frozen=True)
class EvalTask:
    id: str
    mode: EvalMode
    category: str
    description: str
    prompt: str
    fixture: str
    checks: tuple[Check, ...]
    permission_mode: str = "auto"
    attachments: tuple[dict[str, Any], ...] = ()
    script: tuple[tuple[dict[str, Any], ...], ...] | None = None
    history: tuple[dict[str, Any], ...] = ()
    context_window: int | None = None
    timeout_s: float = 60.0


@dataclass
class ToolCallRecord:
    id: str
    name: str
    args: dict[str, Any]
    ok: bool
    error: str | None = None
    error_class: str | None = None
    output: Any = None


@dataclass
class EvalRun:
    task: EvalTask
    repo: FixtureRepo
    events: list[dict[str, Any]] = field(default_factory=list)
    final_text: str = ""
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    llm_messages: list[list[dict[str, Any]]] = field(default_factory=list)
    rounds: int = 0
    duration_ms: int = 0
    usage: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass
class TaskResult:
    task_id: str
    mode: EvalMode
    category: str
    status: TaskStatus
    duration_ms: int = 0
    rounds: int = 0
    tool_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    checks: list[dict[str, Any]] = field(default_factory=list)
    failure: dict[str, Any] | None = None
    error: str | None = None

    @property
    def passed(self) -> bool:
        return self.status == "passed"


@dataclass
class SuiteReport:
    suite: str
    mode: EvalMode
    git_sha: str
    git_dirty: bool
    started_at: str
    finished_at: str
    duration_ms: int
    provider: str | None
    model: str | None
    tasks: list[TaskResult] = field(default_factory=list)
    baseline: dict[str, Any] | None = None

    @property
    def summary(self) -> dict[str, Any]:
        total = len(self.tasks)
        counts = {
            status: sum(1 for task in self.tasks if task.status == status)
            for status in ("passed", "failed", "error", "skipped")
        }
        denominator = max(1, total - counts["skipped"])
        return {
            "total": total,
            **counts,
            "pass_rate": round(counts["passed"] / denominator, 4),
        }

"""Unified verification facts (CAP-01 / CAP-02).

The legacy ``run_verification`` return value is kept for existing callers and
UI.  This module adds a stable report alongside it:

* every profile step is represented, including ``not_run`` steps after an
  earlier required failure;
* results are bound to a workspace snapshot (and the git commit when one is
  available), not just to the model's self-report;
* the execution environment and isolation level are recorded explicitly.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

SCHEMA_VERSION = "verify-1.0"

StepStatus = str  # passed | failed | not_run | skipped | unsupported
ReportStatus = str


@dataclass
class ExecutionEnvironment:
    """Where a verification ran and what isolation it actually had."""

    mode: str                         # container | host | unknown
    isolation: str                    # container | none | unknown
    network: str                      # disabled | enabled | host | unknown
    workdir_scope: str                # repo_snapshot | host_repo | unknown
    env_scrubbed: bool
    image: str = ""
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "isolation": self.isolation,
            "network": self.network,
            "workdir_scope": self.workdir_scope,
            "env_scrubbed": self.env_scrubbed,
            "image": self.image,
            "notes": list(self.notes),
        }


@dataclass
class WorkspaceIdentity:
    """The exact snapshot a verification result belongs to."""

    commit: str = ""
    branch: str = ""
    dirty: bool | None = None
    workspace_digest: str = ""
    diff_digest: str = ""
    source: str = "snapshot"          # git | snapshot

    def to_dict(self) -> dict[str, Any]:
        return {
            "commit": self.commit,
            "branch": self.branch,
            "dirty": self.dirty,
            "workspace_digest": self.workspace_digest,
            "diff_digest": self.diff_digest,
            "source": self.source,
        }


@dataclass
class StepFact:
    name: str
    command: str
    required: bool
    status: StepStatus
    exit_code: int
    timed_out: bool
    duration_ms: int
    reason: str = ""
    stdout: str = ""
    stderr: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "command": self.command,
            "required": self.required,
            "status": self.status,
            "exit_code": self.exit_code,
            "timed_out": self.timed_out,
            "duration_ms": self.duration_ms,
            "reason": self.reason,
            "stdout": self.stdout,
            "stderr": self.stderr,
        }


def _content_hash(value: Any) -> str:
    if isinstance(value, bytes):
        raw = value
    else:
        raw = str(value).encode("utf-8", errors="replace")
    return hashlib.sha256(raw).hexdigest()


def digest_files(files: dict[str, Any] | None) -> str:
    """Stable digest of a path -> content mapping."""
    rows = []
    for path, content in sorted((files or {}).items()):
        rows.append(f"{path}\0{_content_hash(content)}")
    return "sha256:" + hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()


async def describe_workspace(
    repo: dict,
    files: dict[str, Any],
    overrides: dict[str, Any] | None = None,
) -> WorkspaceIdentity:
    """Bind a result to the git HEAD (if any) and the exact file snapshot."""
    identity = WorkspaceIdentity(
        workspace_digest=digest_files(files),
        diff_digest=digest_files(overrides) if overrides else "",
    )
    root = repo.get("root_path")
    if not root:
        return identity
    try:
        from app.core.git_ops.service import status

        info = await status(Path(root))
    except Exception:
        return identity
    if not info.get("available") or not info.get("initialized"):
        return identity
    commits = info.get("commits") or []
    identity.source = "git"
    identity.branch = str(info.get("branch") or "")
    identity.dirty = bool(info.get("dirty"))
    identity.commit = str(commits[0]["hash"]) if commits else ""
    return identity


def container_environment(*, network: str, image: str, notes: Iterable[str] = ()) -> ExecutionEnvironment:
    return ExecutionEnvironment(
        mode="container",
        isolation="container",
        network=network,
        workdir_scope="repo_snapshot",
        env_scrubbed=True,
        image=image,
        notes=list(notes),
    )


def host_environment(*, notes: Iterable[str] = ()) -> ExecutionEnvironment:
    return ExecutionEnvironment(
        mode="host",
        isolation="none",
        network="host",
        workdir_scope="host_repo",
        env_scrubbed=False,
        image="host",
        notes=list(notes),
    )


def unsupported_environment(*, notes: Iterable[str] = ()) -> ExecutionEnvironment:
    return ExecutionEnvironment(
        mode="unknown",
        isolation="unknown",
        network="unknown",
        workdir_scope="unknown",
        env_scrubbed=False,
        notes=list(notes),
    )


def overall_status(steps: Iterable[StepFact | dict[str, Any]]) -> ReportStatus:
    """Failure, not-run, unsupported and skipped are not "passed"."""
    normalized = [
        step if isinstance(step, StepFact) else StepFact(
            name=str(step.get("name") or ""),
            command=str(step.get("command") or ""),
            required=bool(step.get("required", True)),
            status=str(step.get("status") or "not_run"),
            exit_code=int(step.get("exit_code", -1) or -1),
            timed_out=bool(step.get("timed_out")),
            duration_ms=int(step.get("duration_ms", 0) or 0),
            reason=str(step.get("reason") or ""),
            stdout=str(step.get("stdout") or ""),
            stderr=str(step.get("stderr") or ""),
        )
        for step in steps
    ]
    if not normalized:
        return "unsupported"
    required = [step for step in normalized if step.required]
    if any(step.status == "failed" for step in required):
        return "failed"
    if any(step.status == "not_run" for step in required):
        return "not_run"
    if any(step.status == "unsupported" for step in required):
        return "unsupported"
    if any(step.status == "skipped" for step in required):
        return "skipped"
    if any(step.status == "passed" for step in normalized):
        return "passed"
    return "unsupported"


def build_report(
    *,
    stack: str,
    steps: Sequence[StepFact | dict[str, Any]],
    environment: ExecutionEnvironment,
    workspace: WorkspaceIdentity,
    notes: list[str],
    started_at: str,
    elapsed_ms: int,
    command: str = "",
    exit_code: int = -1,
) -> dict[str, Any]:
    facts = [
        step if isinstance(step, StepFact) else StepFact(
            name=str(step.get("name") or ""),
            command=str(step.get("command") or ""),
            required=bool(step.get("required", True)),
            status=str(step.get("status") or "not_run"),
            exit_code=int(step.get("exit_code", -1) or -1),
            timed_out=bool(step.get("timed_out")),
            duration_ms=int(step.get("duration_ms", 0) or 0),
            reason=str(step.get("reason") or ""),
            stdout=str(step.get("stdout") or ""),
            stderr=str(step.get("stderr") or ""),
        )
        for step in steps
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "status": overall_status(facts),
        "stack": stack,
        "environment": environment.to_dict(),
        "workspace": workspace.to_dict(),
        "steps": [step.to_dict() for step in facts],
        "notes": list(notes),
        "started_at": started_at,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_ms": elapsed_ms,
        "command": command,
        "exit_code": exit_code,
    }


def step_reason(
    *,
    status: str,
    exit_code: int,
    timed_out: bool,
    not_run_reason: str = "",
) -> str:
    if not_run_reason:
        return not_run_reason
    if timed_out:
        return "命令超时"
    if status == "passed":
        return ""
    if status == "skipped":
        return "非必需步骤的命令不可用（退出码 127）"
    if status == "unsupported":
        return "当前环境不支持该步骤"
    if exit_code == 127:
        return "命令不存在（退出码 127）"
    if exit_code < 0:
        return "命令未能启动或未返回退出码"
    return f"退出码 {exit_code}"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)

"""CAP-01 / CAP-02 contract tests: unified verification facts."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.config import settings
from app.core.verify import service as verify_service
from app.core.verify.results import (
    StepFact,
    WorkspaceIdentity,
    build_report,
    container_environment,
    digest_files,
    host_environment,
    overall_status,
    step_reason,
)


def _step(name: str, *, required: bool = True, image: str = "python") -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        command=f"run {name}",
        timeout=30,
        required=required,
        image=image,
        network=False,
    )


def _profile(steps: list[SimpleNamespace]) -> SimpleNamespace:
    return SimpleNamespace(
        stack="python",
        steps=steps,
        notes=[],
        unsupported_reason=None,
    )


def test_overall_status_never_hides_failure_or_not_run() -> None:
    assert overall_status([]) == "unsupported"
    assert overall_status([
        StepFact("a", "cmd", True, "passed", 0, False, 1),
    ]) == "passed"
    assert overall_status([
        StepFact("a", "cmd", True, "passed", 0, False, 1),
        StepFact("b", "cmd", True, "failed", 1, False, 1),
    ]) == "failed"
    assert overall_status([
        StepFact("a", "cmd", True, "failed", 1, False, 1),
        StepFact("b", "cmd", True, "not_run", -1, False, 0),
    ]) == "failed"
    assert overall_status([
        StepFact("a", "cmd", True, "not_run", -1, False, 0),
    ]) == "not_run"
    assert overall_status([
        StepFact("a", "cmd", True, "unsupported", -1, False, 0),
    ]) == "unsupported"
    assert overall_status([
        StepFact("a", "cmd", True, "skipped", 127, False, 0),
    ]) == "skipped"


def test_optional_failure_is_visible_but_does_not_fail_the_report() -> None:
    status = overall_status([
        StepFact("required", "cmd", True, "passed", 0, False, 1),
        StepFact("optional", "cmd", False, "failed", 1, False, 1),
    ])
    assert status == "passed"


def test_digest_files_is_stable_and_order_independent() -> None:
    first = digest_files({"b.py": "b", "a.py": "a"})
    second = digest_files({"a.py": "a", "b.py": "b"})
    changed = digest_files({"a.py": "changed", "b.py": "b"})
    assert first == second
    assert first != changed
    assert first.startswith("sha256:")


def test_environment_discloses_isolation_and_network() -> None:
    container = container_environment(network="disabled", image="builder")
    host = host_environment()
    assert container.mode == "container"
    assert container.isolation == "container"
    assert container.network == "disabled"
    assert container.env_scrubbed
    assert host.mode == "host"
    assert host.isolation == "none"
    assert host.network == "host"
    assert not host.env_scrubbed


def test_build_report_contains_schema_version_and_facts() -> None:
    report = build_report(
        stack="python",
        steps=[
            StepFact("unit", "pytest", True, "failed", 1, False, 12, reason="退出码 1"),
            StepFact("lint", "ruff", True, "not_run", -1, False, 0, reason="前序失败"),
        ],
        environment=host_environment(),
        workspace=WorkspaceIdentity(
            workspace_digest="sha256:abc",
            source="snapshot",
        ),
        notes=["本地模式在主机执行，无容器隔离"],
        started_at="2026-11-21T00:00:00+00:00",
        elapsed_ms=42,
        command="pytest → ruff",
        exit_code=1,
    )
    assert report["schema_version"] == "verify-1.0"
    assert report["status"] == "failed"
    assert report["environment"]["isolation"] == "none"
    assert report["workspace"]["workspace_digest"] == "sha256:abc"
    assert report["steps"][1]["status"] == "not_run"
    assert report["steps"][1]["reason"] == "前序失败"


def test_step_reason_distinguishes_timeout_and_missing_tool() -> None:
    assert "超时" in step_reason(status="failed", exit_code=-1, timed_out=True)
    assert "127" in step_reason(status="skipped", exit_code=127, timed_out=False)
    assert step_reason(status="passed", exit_code=0, timed_out=False) == ""
    assert "前序" in step_reason(
        status="not_run",
        exit_code=-1,
        timed_out=False,
        not_run_reason="前序步骤失败",
    )


@pytest.mark.asyncio
async def test_local_verification_report_marks_not_run_steps(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "nova_mode", "local")
    profile = _profile([_step("first"), _step("second"), _step("optional", required=False)])
    monkeypatch.setattr(
        verify_service, "detect_profile", lambda files, **kwargs: profile
    )

    async def fake_collect(repo_id, user):
        return {"app.py": "print(1)"}, {"files": 1, "truncated": False}

    calls: list[str] = []

    async def fake_run_staged(files, command, **kwargs):
        calls.append(command)
        if command == "run first":
            return {"exit_code": 1, "stdout": "", "stderr": "boom", "timed_out": False}
        return {"exit_code": 0, "stdout": "ok", "stderr": "", "timed_out": False}

    monkeypatch.setattr(
        verify_service, "_collect_repo_files_with_stats", fake_collect
    )
    monkeypatch.setattr(verify_service, "run_staged_host", fake_run_staged)

    result = await verify_service.run_verification(
        {"id": "r1", "root_path": str(tmp_path)},
        {"id": 1},
        permission_mode="ask",
        approval_granted=True,
    )

    report = result["report"]
    assert report["status"] == "failed"
    assert report["environment"]["mode"] == "host"
    assert report["environment"]["isolation"] == "none"
    assert report["workspace"]["workspace_digest"].startswith("sha256:")
    assert [step["status"] for step in report["steps"]] == [
        "failed", "not_run", "not_run",
    ]
    assert report["steps"][1]["reason"].startswith("前序必需步骤")
    assert calls == ["run first"]


@pytest.mark.asyncio
async def test_local_verification_denial_is_not_run_in_report(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "nova_mode", "local")
    profile = _profile([_step("first")])
    monkeypatch.setattr(
        verify_service, "detect_profile", lambda files, **kwargs: profile
    )

    async def fake_collect(repo_id, user):
        return {"app.py": "print(1)"}, {"files": 1, "truncated": False}

    monkeypatch.setattr(
        verify_service, "_collect_repo_files_with_stats", fake_collect
    )
    result = await verify_service.run_verification(
        {"id": "r1", "root_path": str(tmp_path)},
        {"id": 1},
        permission_mode="readonly",
    )
    assert result["status"] == "failed"
    assert result["steps"] == []
    assert result["report"]["status"] == "not_run"
    assert result["report"]["steps"][0]["status"] == "not_run"
    assert result["report"]["environment"]["isolation"] == "none"

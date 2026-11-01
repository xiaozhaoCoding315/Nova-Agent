"""Task 9: local verification, red-green tasks and install-deps gating.

Local mode runs verification profiles and red-green phases through the host
executor in a throwaway workspace; Docker-only code must never be reached.
Dependency installation stays disabled unless explicitly enabled in
``nova-config.json`` and, in ask mode, approved for the single call.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.config import settings
from app.core import tasks
from app.core.exec import service
from app.core.security import policy
from app.core.tools import install_deps as install_deps_tool
from app.core.tools.base import ToolBusinessError, ToolContext
from app.core.verify import service as verify_service

REPO_ID = "00000000-0000-0000-0000-000000000001"


def _ctx(**kwargs) -> ToolContext:
    base = dict(
        user={"id": 1, "username": "local", "role": "local"},
        repo_ids=[REPO_ID],
        permission_mode="ask",
    )
    base.update(kwargs)
    return ToolContext(**base)


class _Step:
    name = "单元测试"
    command = "python -m pytest -q"
    timeout = 60
    required = True
    image = "python"
    network = False


def _profile(steps=None, notes=None):
    return SimpleNamespace(
        stack="python",
        steps=[_Step()] if steps is None else steps,
        notes=[] if notes is None else notes,
        unsupported_reason=None,
    )


@pytest.mark.asyncio
async def test_verification_uses_host_workspace(monkeypatch, tmp_path):
    profile = SimpleNamespace(
        stack="python", steps=[_Step()], notes=[], unsupported_reason=None
    )
    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(verify_service, "detect_profile", lambda files: profile)

    async def fake_collect(repo_id, user):
        return {"app.py": "print(1)"}

    async def fake_run_staged(files, command, **kwargs):
        assert kwargs["root"] == str(tmp_path)
        return {"exit_code": 0, "stdout": "ok", "stderr": "", "timed_out": False,
                "isolation": "none", "warning": "无容器隔离"}

    monkeypatch.setattr(verify_service, "_collect_repo_files", fake_collect)
    monkeypatch.setattr(verify_service, "run_staged_host", fake_run_staged)
    result = await verify_service.run_verification(
        {"id": "r1", "root_path": str(tmp_path)}, {"id": 1}
    )
    assert result["status"] == "passed"
    assert result["image"] == "host"
    assert "无容器隔离" in " ".join(result["notes"])


@pytest.mark.asyncio
async def test_run_staged_host_runs_pytest_in_temp_workspace(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(settings, "nova_data_dir", str(tmp_path / "NovaData"))
    files = {"test_sample.py": "def test_ok():\n    assert 1 + 1 == 2\n"}
    result = await service.run_staged_host(
        files,
        f'"{sys.executable}" -m pytest -q',
        root=tmp_path,
        timeout=60,
    )
    assert result["exit_code"] == 0
    assert result["isolation"] == "none"
    assert list((tmp_path / "NovaData" / "tmp").iterdir()) == []


@pytest.mark.asyncio
async def test_run_staged_host_skips_secret_and_traversal_files(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(settings, "nova_data_dir", str(tmp_path / "NovaData"))
    written: list[str] = []

    async def fake_execute(command, **kwargs):
        root = Path(kwargs["root"])
        written.extend(p.name for p in root.rglob("*"))
        return {"exit_code": 0, "stdout": "", "stderr": "", "timed_out": False}

    monkeypatch.setattr(service, "execute_host", fake_execute)
    await service.run_staged_host(
        {"../escape.py": "x", ".env": "SECRET=1", "app.py": "print(1)"},
        "python app.py",
        root=tmp_path,
        timeout=5,
    )
    assert "app.py" in written
    assert "escape.py" not in written
    assert ".env" not in written
    assert list((tmp_path / "NovaData" / "tmp").iterdir()) == []


@pytest.mark.asyncio
async def test_run_staged_host_missing_data_dir_is_business_error(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(settings, "nova_data_dir", "")
    monkeypatch.setattr(settings, "local_tmp_dir", "")
    with pytest.raises(ToolBusinessError, match="本地执行失败"):
        await service.run_staged_host({"app.py": "print(1)"}, "python app.py", root=tmp_path)


@pytest.mark.asyncio
async def test_task_sandbox_run_uses_host(monkeypatch, tmp_path):
    called: dict = {}

    async def fake_run_staged(files, command, **kwargs):
        called.update(files=files, command=command, **kwargs)
        return {"exit_code": 1, "stdout": "", "stderr": "red", "timed_out": False,
                "isolation": "none", "warning": service.WARNING}

    async def fake_audit(*args, **kwargs):
        return None

    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr("app.core.tasks.engine.run_staged_host", fake_run_staged)
    monkeypatch.setattr("app.core.tasks.engine.log_audit", fake_audit)
    result = await tasks.engine._sandbox_run(
        "task-1", {"id": 1}, "repo-1", tmp_path,
        {"app.py": "print(1)"}, {"test_app.py": "def test_x(): pass"},
        "python -m pytest -q",
    )
    assert result["exit_code"] == 1
    assert called["root"] == tmp_path
    assert called["command"] == "python -m pytest -q"
    assert result["warning"] == service.WARNING


@pytest.mark.asyncio
async def test_install_deps_local_disabled_by_default(monkeypatch):
    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(settings, "local_allow_install_deps", False)
    with pytest.raises(ToolBusinessError, match="默认禁用"):
        await install_deps_tool.install_deps({}, _ctx())


@pytest.mark.asyncio
async def test_install_deps_local_requires_approval(monkeypatch):
    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(settings, "local_allow_install_deps", True)
    with pytest.raises(ToolBusinessError, match="批准"):
        await install_deps_tool.install_deps({}, _ctx(approval_granted=False))


@pytest.mark.asyncio
async def test_install_deps_local_uses_project_venv(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(settings, "local_allow_install_deps", True)
    (tmp_path / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    seen: dict = {}

    async def fake_get_repo(repo_id, user_id):
        return {"id": repo_id, "root_path": str(tmp_path), "origin": "local"}

    def fake_read(root, rel):
        return "pytest\n"

    async def fake_execute(command, **kwargs):
        seen.update(command=command, **kwargs)
        return {"exit_code": 0, "stdout": "installed", "stderr": "",
                "timed_out": False, "isolation": "none"}

    async def fake_audit(*args, **kwargs):
        return None

    monkeypatch.setattr(install_deps_tool, "get_repo", fake_get_repo)
    monkeypatch.setattr(install_deps_tool, "_read_repo_file", fake_read)
    monkeypatch.setattr(install_deps_tool, "project_python", lambda root: tmp_path / "python.exe")
    monkeypatch.setattr(install_deps_tool, "execute_host", fake_execute)
    monkeypatch.setattr(install_deps_tool, "log_audit", fake_audit)
    result = await install_deps_tool.install_deps({}, _ctx(approval_granted=True))
    assert result["installed"] is True
    assert str(tmp_path / "python.exe") in seen["command"]
    assert "-m pip install -r" in seen["command"]


@pytest.mark.asyncio
async def test_install_deps_local_node_uses_lockfile(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(settings, "local_allow_install_deps", True)
    seen: dict = {}

    async def fake_get_repo(repo_id, user_id):
        return {"id": repo_id, "root_path": str(tmp_path), "origin": "local"}

    def fake_read(root, rel):
        return {
            "package.json": "{}",
            "package-lock.json": "{}",
        }.get(rel)

    async def fake_execute(command, **kwargs):
        seen.update(command=command, **kwargs)
        return {"exit_code": 0, "stdout": "ok", "stderr": "", "timed_out": False}

    async def fake_audit(*args, **kwargs):
        return None

    monkeypatch.setattr(install_deps_tool, "get_repo", fake_get_repo)
    monkeypatch.setattr(install_deps_tool, "_read_repo_file", fake_read)
    monkeypatch.setattr(install_deps_tool, "execute_host", fake_execute)
    monkeypatch.setattr(install_deps_tool, "log_audit", fake_audit)
    result = await install_deps_tool.install_deps(
        {"kind": "node"}, _ctx(approval_granted=True)
    )
    assert result["installed"] is True
    assert result["kind"] == "node"
    assert seen["command"] == "npm ci --no-audit --no-fund"
    assert str(seen["root"]) == str(tmp_path)


def test_policy_local_install_deps_requires_approval(monkeypatch):
    from app.config import settings as live_settings

    monkeypatch.setattr(live_settings, "nova_mode", "local")
    monkeypatch.setattr(live_settings, "local_allow_install_deps", False)
    denied = policy.decide_tool("install_deps", "execute", None, {}, _ctx())
    assert denied.allowed is False
    assert "默认禁用" in denied.reason

    monkeypatch.setattr(live_settings, "local_allow_install_deps", True)
    approval = policy.decide_tool("install_deps", "execute", None, {}, _ctx())
    assert approval.allowed is False
    assert approval.requires_approval is True
    allowed = policy.decide_tool(
        "install_deps", "execute", None, {}, _ctx(approval_granted=True)
    )
    assert allowed.allowed is True


# ---------------------------------------------------------------------------
# Carry-forward gates: local readonly never runs host commands; ask needs
# explicit approval for verify and install_deps.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_local_verification_surfaces_kill_warning(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(verify_service, "detect_profile", lambda files: _profile())

    async def fake_collect(repo_id, user):
        return {"app.py": "print(1)"}

    async def fake_run_staged(files, command, **kwargs):
        return {"exit_code": 0, "stdout": "ok", "stderr": "", "timed_out": True,
                "kill_failed": True, "isolation": "none"}

    monkeypatch.setattr(verify_service, "_collect_repo_files", fake_collect)
    monkeypatch.setattr(verify_service, "run_staged_host", fake_run_staged)
    result = await verify_service.run_verification(
        {"id": "r1", "root_path": str(tmp_path)}, {"id": 1}
    )
    assert result["status"] == "failed"
    assert any("残留进程" in note for note in result["notes"])


@pytest.mark.asyncio
async def test_local_verification_readonly_never_runs_host(monkeypatch, tmp_path):
    called = {"host": 0}
    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(verify_service, "detect_profile", lambda files: _profile())

    async def fake_collect(repo_id, user):
        return {"app.py": "print(1)"}

    async def fake_run_staged(files, command, **kwargs):
        called["host"] += 1
        return {"exit_code": 0, "stdout": "ok", "stderr": "", "timed_out": False}

    monkeypatch.setattr(verify_service, "_collect_repo_files", fake_collect)
    monkeypatch.setattr(verify_service, "run_staged_host", fake_run_staged)
    result = await verify_service.run_verification(
        {"id": "r1", "root_path": str(tmp_path)}, {"id": 1},
        permission_mode="readonly",
    )
    assert result["status"] == "failed"
    assert "只读" in result["stderr"]
    assert result["steps"] == []
    assert result["image"] == "host"
    assert called["host"] == 0


@pytest.mark.asyncio
async def test_local_verification_ask_requires_approval(monkeypatch, tmp_path):
    called = {"host": 0}
    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(verify_service, "detect_profile", lambda files: _profile())

    async def fake_collect(repo_id, user):
        return {"app.py": "print(1)"}

    async def fake_run_staged(files, command, **kwargs):
        called["host"] += 1
        return {"exit_code": 0, "stdout": "ok", "stderr": "", "timed_out": False}

    monkeypatch.setattr(verify_service, "_collect_repo_files", fake_collect)
    monkeypatch.setattr(verify_service, "run_staged_host", fake_run_staged)

    denied = await verify_service.run_verification(
        {"id": "r1", "root_path": str(tmp_path)}, {"id": 1}, permission_mode="ask"
    )
    assert denied["status"] == "failed"
    assert "批准" in denied["stderr"]
    assert called["host"] == 0

    approved = await verify_service.run_verification(
        {"id": "r1", "root_path": str(tmp_path)}, {"id": 1},
        permission_mode="ask", approval_granted=True,
    )
    assert approved["status"] == "passed"
    assert called["host"] == 1


@pytest.mark.asyncio
async def test_install_deps_local_readonly_denied(monkeypatch):
    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(settings, "local_allow_install_deps", True)
    with pytest.raises(ToolBusinessError, match="只读"):
        await install_deps_tool.install_deps(
            {}, _ctx(permission_mode="readonly", approval_granted=True)
        )


def test_local_install_deps_description_is_honest(monkeypatch):
    monkeypatch.setattr(settings, "nova_mode", "local")
    local = install_deps_tool.tool_description()
    assert "默认禁用" in local
    assert "批准" in local
    assert "仅管理员" not in local

    monkeypatch.setattr(settings, "nova_mode", "server")
    assert "仅管理员" in install_deps_tool.tool_description()


def test_policy_local_install_deps_readonly_flat_denied(monkeypatch):
    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(settings, "local_allow_install_deps", True)
    decision = policy.decide_tool(
        "install_deps", "execute", None, {},
        _ctx(permission_mode="readonly", approval_granted=True),
    )
    assert decision.allowed is False
    assert decision.requires_approval is False
    assert "只读" in decision.reason


@pytest.mark.asyncio
async def test_local_verify_endpoint_uses_host_flow(monkeypatch):
    """The verify endpoint no longer rejects local mode (Task 8 message)."""
    from app.api.v1 import builder as builder_api

    monkeypatch.setattr(settings, "nova_mode", "local")
    seen: dict = {}

    async def fake_get_repo(repo_id, user_id):
        return {"id": repo_id, "root_path": "C:/repo", "status": "ready"}

    async def fake_enqueue(repo_id, user_id, **kwargs):
        seen.update(repo_id=repo_id, user_id=user_id, **kwargs)
        return "job-1"

    async def fail_status():  # pragma: no cover - must not run
        raise AssertionError("Docker status must not be consulted locally")

    monkeypatch.setattr(builder_api, "get_repo", fake_get_repo)
    monkeypatch.setattr(builder_api, "enqueue_verify", fake_enqueue)
    monkeypatch.setattr(builder_api, "sandbox_status", fail_status)

    result = await builder_api.verify_repo(REPO_ID, user={"id": 1, "role": "local"})
    assert result == {"ok": True, "job_id": "job-1"}
    assert seen["permission_mode"] == "ask"
    assert seen["approval_granted"] is True

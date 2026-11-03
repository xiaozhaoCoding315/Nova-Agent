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
from app.core.exec.host import execute_host, quote_shell_arg
from app.core.jobs.models import JobCanceled
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
    monkeypatch.setattr(
        verify_service, "detect_profile", lambda files, **kwargs: profile
    )

    async def fake_collect(repo_id, user):
        return {"app.py": "print(1)"}, {"files": 1, "truncated": False}

    async def fake_run_staged(files, command, **kwargs):
        assert kwargs["root"] == str(tmp_path)
        return {"exit_code": 0, "stdout": "ok", "stderr": "", "timed_out": False,
                "isolation": "none", "warning": "无容器隔离"}

    monkeypatch.setattr(
        verify_service, "_collect_repo_files_with_stats", fake_collect
    )
    monkeypatch.setattr(verify_service, "run_staged_host", fake_run_staged)
    result = await verify_service.run_verification(
        {"id": "r1", "root_path": str(tmp_path)}, {"id": 1},
        permission_mode="ask", approval_granted=True,
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
    assert "临时" in result["warning"]
    assert "项目目录" not in result["warning"]
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
    monkeypatch.setattr(
        verify_service, "detect_profile", lambda files, **kwargs: _profile()
    )

    async def fake_collect(repo_id, user):
        return {"app.py": "print(1)"}, {"files": 1, "truncated": False}

    async def fake_run_staged(files, command, **kwargs):
        return {"exit_code": 0, "stdout": "ok", "stderr": "", "timed_out": True,
                "kill_failed": True, "isolation": "none"}

    monkeypatch.setattr(
        verify_service, "_collect_repo_files_with_stats", fake_collect
    )
    monkeypatch.setattr(verify_service, "run_staged_host", fake_run_staged)
    result = await verify_service.run_verification(
        {"id": "r1", "root_path": str(tmp_path)}, {"id": 1},
        permission_mode="ask", approval_granted=True,
    )
    assert result["status"] == "failed"
    assert any("残留进程" in note for note in result["notes"])


@pytest.mark.asyncio
async def test_local_verification_readonly_never_runs_host(monkeypatch, tmp_path):
    called = {"host": 0}
    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(
        verify_service, "detect_profile", lambda files, **kwargs: _profile()
    )

    async def fake_collect(repo_id, user):
        return {"app.py": "print(1)"}, {"files": 1, "truncated": False}

    async def fake_run_staged(files, command, **kwargs):
        called["host"] += 1
        return {"exit_code": 0, "stdout": "ok", "stderr": "", "timed_out": False}

    monkeypatch.setattr(
        verify_service, "_collect_repo_files_with_stats", fake_collect
    )
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
    monkeypatch.setattr(
        verify_service, "detect_profile", lambda files, **kwargs: _profile()
    )

    async def fake_collect(repo_id, user):
        return {"app.py": "print(1)"}, {"files": 1, "truncated": False}

    async def fake_run_staged(files, command, **kwargs):
        called["host"] += 1
        return {"exit_code": 0, "stdout": "ok", "stderr": "", "timed_out": False}

    monkeypatch.setattr(
        verify_service, "_collect_repo_files_with_stats", fake_collect
    )
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
async def test_local_verification_default_mode_requires_approval(monkeypatch, tmp_path):
    """Omitting permission_mode must not silently run host commands locally."""
    called = {"host": 0}
    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(
        verify_service, "detect_profile", lambda files, **kwargs: _profile()
    )

    async def fake_collect(repo_id, user):
        return {"app.py": "print(1)"}, {"files": 1, "truncated": False}

    async def fake_run_staged(files, command, **kwargs):
        called["host"] += 1
        return {"exit_code": 0, "stdout": "ok", "stderr": "", "timed_out": False}

    monkeypatch.setattr(
        verify_service, "_collect_repo_files_with_stats", fake_collect
    )
    monkeypatch.setattr(verify_service, "run_staged_host", fake_run_staged)
    result = await verify_service.run_verification(
        {"id": "r1", "root_path": str(tmp_path)}, {"id": 1}
    )
    assert result["status"] == "failed"
    assert "批准" in result["stderr"]
    assert called["host"] == 0


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
    # The generic WRITE_CAPABILITIES gate is what denies this, not a local
    # install-specific branch; assert its actual wording so removing either
    # gate is caught.
    assert "计划（只读）模式" in decision.reason
    assert "已阻止 install_deps" in decision.reason


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


# ---------------------------------------------------------------------------
# Fix pass: safe quoting, Node gate, truncation note and cancellation.
# ---------------------------------------------------------------------------


def test_quote_shell_arg_quotes_spaces_per_platform():
    assert quote_shell_arg("plain", platform="posix") == "plain"
    assert quote_shell_arg("my dir/x.py", platform="posix") == "'my dir/x.py'"
    assert quote_shell_arg("plain", platform="win32") == '"plain"'
    assert quote_shell_arg("C:/my repo/app.py", platform="win32") == (
        '"C:/my repo/app.py"'
    )


@pytest.mark.parametrize(
    "value",
    ["a&b", "a|b", "a<b", "a>b", "a(b)", "a^b", "a%b", "a!b", 'a"b'],
)
def test_quote_shell_arg_windows_rejects_shell_syntax(value):
    with pytest.raises(ValueError):
        quote_shell_arg(value, platform="win32")


@pytest.mark.parametrize("platform", ["win32", "posix"])
def test_quote_shell_arg_rejects_newlines_everywhere(platform):
    with pytest.raises(ValueError):
        quote_shell_arg("a\nb", platform=platform)
    with pytest.raises(ValueError):
        quote_shell_arg("a\rb", platform=platform)


@pytest.mark.asyncio
async def test_quoted_path_with_space_runs_on_host(tmp_path):
    """A legitimate path with spaces survives real shell parsing."""
    workdir = tmp_path / "space dir"
    workdir.mkdir()
    target = workdir / "hello world.txt"
    target.write_text("ok-from-space", encoding="utf-8")
    command = (
        f"{quote_shell_arg(sys.executable)} -c "
        "\"import sys;print(open(sys.argv[1], encoding='utf-8').read())\" "
        f"{quote_shell_arg(str(target))}"
    )
    result = await execute_host(command, root=workdir, timeout=60)
    assert result["exit_code"] == 0, result["stderr"]
    assert "ok-from-space" in result["stdout"]


@pytest.mark.asyncio
async def test_run_staged_host_rejects_multiline(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(settings, "nova_data_dir", str(tmp_path / "NovaData"))
    with pytest.raises(ToolBusinessError, match="换行"):
        await service.run_staged_host(
            {"app.py": "print(1)"}, "python app.py\necho injected", root=tmp_path
        )
    assert not (tmp_path / "NovaData" / "tmp").exists()


@pytest.mark.asyncio
async def test_contract_source_cannot_inject_local_command(monkeypatch, tmp_path):
    """nova.yaml comes from the repo; it must never become cmd.exe syntax."""
    from app.core.verify.profiles import detect_profile as real_detect_profile

    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(
        verify_service, "detect_profile",
        lambda files, **kwargs: real_detect_profile(files, platform="win32"),
    )
    commands: list[str] = []

    async def fake_collect(repo_id, user):
        return (
            {
                "app.py": "print(1)",
                "tests/test_app.py": "def test_ok(): pass",
                "nova.yaml": (
                    "contract:\n"
                    "  source: \"x & echo NOVA_INJECTED & rem\"\n"
                ),
            },
            {"files": 3, "truncated": False},
        )

    async def fake_run_staged(files, command, **kwargs):
        commands.append(command)
        return {"exit_code": 0, "stdout": "", "stderr": "", "timed_out": False}

    monkeypatch.setattr(
        verify_service, "_collect_repo_files_with_stats", fake_collect
    )
    monkeypatch.setattr(verify_service, "run_staged_host", fake_run_staged)
    result = await verify_service.run_verification(
        {"id": "r1", "root_path": str(tmp_path)}, {"id": 1},
        permission_mode="ask", approval_granted=True,
    )
    assert result["status"] == "passed"
    assert commands  # Python steps still ran
    assert not any("NOVA_INJECTED" in command for command in commands)
    assert any("契约检查已跳过" in note for note in result["notes"])


@pytest.mark.asyncio
async def test_local_verification_gates_node_profile(monkeypatch, tmp_path):
    node_step = SimpleNamespace(
        name="Node 测试", command="CI=1 npm test", timeout=60,
        required=True, image="node", network=False,
    )
    profile = SimpleNamespace(
        stack="fullstack",
        steps=[_Step(), node_step],
        notes=["同时检测到 Python 与 Node：Python 步骤使用 builder 镜像，Node 步骤使用 node 镜像"],
        unsupported_reason=None,
    )
    called = {"host": 0}
    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(
        verify_service, "detect_profile", lambda files, **kwargs: profile
    )

    async def fake_collect(repo_id, user):
        return {"app.py": "print(1)"}, {"files": 1, "truncated": False}

    async def fake_run_staged(files, command, **kwargs):
        called["host"] += 1
        return {"exit_code": 0, "stdout": "", "stderr": "", "timed_out": False}

    monkeypatch.setattr(
        verify_service, "_collect_repo_files_with_stats", fake_collect
    )
    monkeypatch.setattr(verify_service, "run_staged_host", fake_run_staged)
    result = await verify_service.run_verification(
        {"id": "r1", "root_path": str(tmp_path)}, {"id": 1},
        permission_mode="ask", approval_granted=True,
    )
    # Node 步骤现在真的在主机上执行，而不是整组判为 unsupported。
    assert result["status"] == "passed"
    assert result["image"] == "host"
    assert called["host"] == len(profile.steps)
    assert all(step["status"] == "passed" for step in result["steps"])
    assert not any("暂不支持" in note for note in result["notes"])
    assert not any("镜像" in note for note in result["notes"])


@pytest.mark.asyncio
async def test_local_verification_strips_docker_image_notes(monkeypatch, tmp_path):
    profile = SimpleNamespace(
        stack="python",
        steps=[_Step()],
        notes=["Python 步骤使用 builder 镜像"],
        unsupported_reason=None,
    )
    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(
        verify_service, "detect_profile", lambda files, **kwargs: profile
    )

    async def fake_collect(repo_id, user):
        return {"app.py": "print(1)"}, {"files": 1, "truncated": False}

    async def fake_run_staged(files, command, **kwargs):
        return {"exit_code": 0, "stdout": "", "stderr": "", "timed_out": False}

    monkeypatch.setattr(
        verify_service, "_collect_repo_files_with_stats", fake_collect
    )
    monkeypatch.setattr(verify_service, "run_staged_host", fake_run_staged)
    result = await verify_service.run_verification(
        {"id": "r1", "root_path": str(tmp_path)}, {"id": 1},
        permission_mode="ask", approval_granted=True,
    )
    assert result["status"] == "passed"
    assert not any("镜像" in note for note in result["notes"])
    assert verify_service.LOCAL_HOST_NOTE in result["notes"]


@pytest.mark.asyncio
async def test_local_verification_notes_truncated_repo_copy(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(
        verify_service, "detect_profile", lambda files, **kwargs: _profile()
    )

    async def fake_collect(repo_id, user):
        return {"app.py": "print(1)"}, {"files": 300, "truncated": True}

    async def fake_run_staged(files, command, **kwargs):
        return {"exit_code": 0, "stdout": "", "stderr": "", "timed_out": False}

    monkeypatch.setattr(
        verify_service, "_collect_repo_files_with_stats", fake_collect
    )
    monkeypatch.setattr(verify_service, "run_staged_host", fake_run_staged)
    result = await verify_service.run_verification(
        {"id": "r1", "root_path": str(tmp_path)}, {"id": 1},
        permission_mode="ask", approval_granted=True,
    )
    assert result["status"] == "passed"
    assert verify_service.TRUNCATED_NOTE in result["notes"]


@pytest.mark.asyncio
async def test_local_verification_cancels_between_steps(monkeypatch, tmp_path):
    second = SimpleNamespace(
        name="第二项", command="python -m pip --version", timeout=60,
        required=True, image="python", network=False,
    )
    profile = SimpleNamespace(
        stack="python",
        steps=[_Step(), second],
        notes=[],
        unsupported_reason=None,
    )
    commands: list[str] = []
    checks = {"n": 0}
    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(
        verify_service, "detect_profile", lambda files, **kwargs: profile
    )

    async def fake_collect(repo_id, user):
        return {"app.py": "print(1)"}, {"files": 1, "truncated": False}

    async def fake_run_staged(files, command, **kwargs):
        commands.append(command)
        return {"exit_code": 0, "stdout": "", "stderr": "", "timed_out": False}

    async def maybe_cancel(job_id):
        checks["n"] += 1
        return checks["n"] > 1

    monkeypatch.setattr(
        verify_service, "_collect_repo_files_with_stats", fake_collect
    )
    monkeypatch.setattr(verify_service, "run_staged_host", fake_run_staged)
    from app.core.jobs.runner import runner as job_runner

    monkeypatch.setattr(job_runner, "is_cancel_requested", maybe_cancel)
    with pytest.raises(JobCanceled):
        await verify_service.run_verification(
            {"id": "r1", "root_path": str(tmp_path)}, {"id": 1},
            permission_mode="ask", approval_granted=True, job_id="job-1",
        )
    assert commands == [_Step.command]


def test_task_commands_use_host_quoting(monkeypatch):
    monkeypatch.setattr(settings, "nova_mode", "local")
    red = tasks.engine._pytest_command(["pkg/test a.py"], "pkg")
    assert red.startswith(f"cd {quote_shell_arg('pkg')} && ")
    # The root prefix is stripped from test paths before quoting.
    assert quote_shell_arg("test a.py") in red
    green = tasks.engine._full_suite_command("pkg")
    assert green.startswith(f"cd {quote_shell_arg('pkg')} && ")
    assert "python -m compileall -q ." in green


@pytest.mark.asyncio
async def test_install_deps_local_quotes_manifest_with_space(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(settings, "local_allow_install_deps", True)
    seen: dict = {}

    async def fake_get_repo(repo_id, user_id):
        return {"id": repo_id, "root_path": str(tmp_path), "origin": "local"}

    def fake_read(root, rel):
        return "pytest\n"

    async def fake_execute(command, **kwargs):
        seen.update(command=command, **kwargs)
        return {"exit_code": 0, "stdout": "installed", "stderr": ""}

    async def fake_audit(*args, **kwargs):
        return None

    monkeypatch.setattr(install_deps_tool, "get_repo", fake_get_repo)
    monkeypatch.setattr(install_deps_tool, "_read_repo_file", fake_read)
    monkeypatch.setattr(
        install_deps_tool, "project_python", lambda root: tmp_path / "python.exe"
    )
    monkeypatch.setattr(install_deps_tool, "execute_host", fake_execute)
    monkeypatch.setattr(install_deps_tool, "log_audit", fake_audit)
    result = await install_deps_tool.install_deps(
        {"requirements": "requirements dev.txt"}, _ctx(approval_granted=True)
    )
    assert result["installed"] is True
    assert quote_shell_arg("requirements dev.txt") in seen["command"]
    assert str(tmp_path / "python.exe") in seen["command"]
    # 本地 Node 验证已按平台生成命令，不再提示「暂不支持」。
    assert "暂不支持" not in result["hint"]
    assert ".venv" in result["hint"]


@pytest.mark.skipif(
    sys.platform != "win32", reason="cmd.exe metacharacter rejection is Windows-only"
)
@pytest.mark.asyncio
async def test_install_deps_local_rejects_shell_syntax_manifest(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(settings, "local_allow_install_deps", True)

    async def fake_get_repo(repo_id, user_id):
        return {"id": repo_id, "root_path": str(tmp_path), "origin": "local"}

    monkeypatch.setattr(install_deps_tool, "get_repo", fake_get_repo)
    monkeypatch.setattr(install_deps_tool, "_read_repo_file", lambda root, rel: "x")
    monkeypatch.setattr(
        install_deps_tool, "project_python", lambda root: tmp_path / "python.exe"
    )
    with pytest.raises(ToolBusinessError, match="路径不安全"):
        await install_deps_tool.install_deps(
            {"requirements": "req & echo NOVA_INJECTED"}, _ctx(approval_granted=True)
        )

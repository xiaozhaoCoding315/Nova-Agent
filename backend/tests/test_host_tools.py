"""Host executor wiring: local run_command / run_code, status and cancel.

Server-mode behavior is untouched: every local branch is behind
``settings.use_host_executor`` and the policy gate still runs inside
``ToolRegistry.execute`` before any host execution.
"""
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.config import settings
from app.core.exec import service
from app.core.sandbox import runtime as sandbox_runtime
from app.core.tools import get_registry
from app.core.tools import run_code as run_code_tool
from app.core.tools import run_command as run_command_tool
from app.core.tools.base import ToolBusinessError, ToolContext

REPO_ID = "00000000-0000-0000-0000-000000000001"


def _ctx(user_id=1, **kwargs) -> ToolContext:
    return ToolContext(
        user={"id": user_id, "username": "local", "role": "local"},
        repo_ids=[REPO_ID],
        repo_roots={},
        session_id="00000000-0000-0000-0000-000000000002",
        **kwargs,
    )


def _host_result(**extra):
    base = {
        "stdout": "ok", "stderr": "", "exit_code": 0, "timed_out": False,
        "sandboxed": False, "isolation": "none", "executor": "host",
        "duration_ms": 1,
    }
    base.update(extra)
    return base


@pytest.mark.asyncio
async def test_sandbox_status_local_reports_host(monkeypatch):
    monkeypatch.setattr(settings, "nova_mode", "local")
    status = await sandbox_runtime.sandbox_status()
    assert status["available"] is True
    assert status["executor"] == "host"
    assert status["isolation"] == "none"


@pytest.mark.asyncio
async def test_sandbox_status_local_probes_host_path(monkeypatch):
    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(
        sandbox_runtime.shutil,
        "which",
        lambda name: "C:/Program Files/nodejs/node.exe" if name == "node" else None,
    )
    status = await sandbox_runtime.sandbox_status()
    assert status["available"] is True
    assert status["node_available"] is True
    assert status["builder_available"] is False
    assert status["default_available"] is False


@pytest.mark.asyncio
async def test_sandbox_status_local_never_advertises_builder(monkeypatch):
    """The builder image is blocked locally even when Python is installed."""
    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(
        sandbox_runtime.shutil,
        "which",
        lambda name: "C:/Python/python.exe" if name in ("python", "python3") else None,
    )
    status = await sandbox_runtime.sandbox_status()
    assert status["default_available"] is True
    assert status["builder_available"] is False


@pytest.mark.asyncio
async def test_sandbox_status_server_mode_unchanged(monkeypatch):
    monkeypatch.setattr(settings, "nova_mode", "server")
    monkeypatch.setattr(sandbox_runtime, "is_docker_available", lambda: False)
    status = await sandbox_runtime.sandbox_status()
    assert status["available"] is False
    assert "reason" in status
    assert "executor" not in status
    assert "isolation" not in status


@pytest.mark.asyncio
async def test_kill_job_containers_local_uses_host_registry(monkeypatch):
    monkeypatch.setattr(settings, "nova_mode", "local")
    calls: list[tuple] = []

    async def fake_cancel(job_id, user_id=None):
        calls.append((job_id, user_id))
        return 2

    monkeypatch.setattr("app.core.exec.host.cancel_host_processes", fake_cancel)
    assert await sandbox_runtime.kill_job_containers("tool-1", 7) == 2
    assert calls == [("tool-1", 7)]


@pytest.mark.asyncio
async def test_run_command_host_marks_result(monkeypatch, tmp_path):
    seen: dict = {}

    async def fake_execute(command, **kwargs):
        seen.update(command=command, **kwargs)
        return _host_result(command=command)

    monkeypatch.setattr(service, "execute_host", fake_execute)
    result = await service.run_command_host(
        "echo ok", root=tmp_path, timeout=5, job_id="tool-9", user_id=7
    )
    assert seen["job_id"] == "tool-9"
    assert seen["user_id"] == 7
    assert result["sandboxed"] is False
    assert result["isolation"] == "none"
    assert result["warning"] == (
        "本地执行无容器隔离：命令以当前 Windows 用户权限在你的项目目录运行"
    )
    assert result["warning"] == service.WARNING


@pytest.mark.asyncio
async def test_run_command_host_rejects_multiline(monkeypatch, tmp_path):
    async def fail_execute(command, **kwargs):  # pragma: no cover - must not run
        raise AssertionError("must not execute")

    monkeypatch.setattr(service, "execute_host", fail_execute)
    with pytest.raises(ToolBusinessError) as exc:
        await service.run_command_host(
            "echo a\necho b", root=tmp_path, timeout=5
        )
    assert "多行" in str(exc.value)


@pytest.mark.asyncio
async def test_run_command_host_maps_executor_errors(monkeypatch, tmp_path):
    async def raise_value_error(command, **kwargs):
        raise ValueError("cwd 越出项目目录")

    monkeypatch.setattr(service, "execute_host", raise_value_error)
    with pytest.raises(ToolBusinessError):
        await service.run_command_host("echo ok", root=tmp_path, timeout=5)

    async def raise_os_error(command, **kwargs):
        raise OSError("spawn failed")

    monkeypatch.setattr(service, "execute_host", raise_os_error)
    with pytest.raises(ToolBusinessError):
        await service.run_command_host("echo ok", root=tmp_path, timeout=5)


@pytest.mark.asyncio
async def test_run_command_host_surfaces_kill_failed_warning(monkeypatch, tmp_path):
    async def fake_execute(command, **kwargs):
        return _host_result(command=command, kill_failed=True, timed_out=True)

    monkeypatch.setattr(service, "execute_host", fake_execute)
    result = await service.run_command_host("ping -n 30 127.0.0.1", root=tmp_path, timeout=5)
    assert "未能完全结束" in result["warning"]
    assert "本地执行无容器隔离" in result["warning"]
    assert result["kill_failed"] is True


@pytest.mark.asyncio
async def test_run_command_local_branch_executes_in_project(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(settings, "nova_data_dir", str(tmp_path / "NovaData"))

    async def fake_get_repo(repo_id, user_id):
        return {"id": repo_id, "root_path": str(tmp_path), "origin": "local"}

    monkeypatch.setattr("app.core.indexing.pipeline.get_repo", fake_get_repo)
    command = f'"{sys.executable}" -c "print(42)"'
    result = await run_command_tool.run_command(
        {"command": command, "repo_id": REPO_ID},
        _ctx(),
    )
    assert result["stdout"].strip() == "42"
    assert result["persisted"] is True
    assert result["isolation"] == "none"
    assert result["warning"]


@pytest.mark.asyncio
async def test_local_run_command_never_bypasses_policy_gate(monkeypatch, tmp_path):
    """Requirement 1: ask-mode approval still applies before host execution."""
    called = {"host": False}

    async def fail_execute(command, **kwargs):  # pragma: no cover - must not run
        called["host"] = True
        raise AssertionError("host executor must not run before approval")

    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(service, "execute_host", fail_execute)
    result = await get_registry().execute(
        "run_command",
        {"command": "rm -rf build", "repo_id": REPO_ID},
        _ctx(permission_mode="ask"),
    )
    assert result["ok"] is False
    assert result.get("requires_approval")
    assert called["host"] is False


@pytest.mark.asyncio
async def test_local_ask_run_code_requires_approval_before_execution(monkeypatch, tmp_path):
    """C1: local ask-mode run_code must prompt and never execute first."""
    called = {"host": 0}

    async def fake_execute(command, **kwargs):
        called["host"] += 1
        return _host_result(command=command)

    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(settings, "nova_data_dir", str(tmp_path / "NovaData"))
    monkeypatch.setattr(service, "execute_host", fake_execute)
    ctx = _ctx(permission_mode="ask")

    result = await get_registry().execute(
        "run_code", {"files": {"main.py": "print(1)"}}, ctx
    )
    assert result["ok"] is False
    assert result["requires_approval"]["name"] == "run_code"
    assert "本地模式" in result["requires_approval"]["reason"]
    assert called["host"] == 0

    ctx.approval_granted = True
    approved = await get_registry().execute(
        "run_code", {"files": {"main.py": "print(1)"}}, ctx
    )
    assert approved["ok"] is True
    assert approved["output"]["executor"] == "host"
    assert called["host"] == 1


@pytest.mark.asyncio
async def test_local_readonly_run_command_denied_before_host(monkeypatch):
    """I3: local readonly has no sanitized copy, so shell is flat-denied."""
    called = {"host": 0}

    async def fake_execute(command, **kwargs):
        called["host"] += 1
        return _host_result(command=command)

    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(service, "execute_host", fake_execute)

    result = await get_registry().execute(
        "run_command",
        {"command": "grep -r API_KEY .", "repo_id": REPO_ID},
        _ctx(permission_mode="readonly"),
    )
    assert result["ok"] is False
    assert result["business"] is True
    assert "切换到确认模式" in result["error"]
    assert "requires_approval" not in result
    assert called["host"] == 0


@pytest.mark.asyncio
async def test_local_readonly_run_code_denied_before_host(monkeypatch):
    called = {"host": 0}

    async def fake_execute(command, **kwargs):
        called["host"] += 1
        return _host_result(command=command)

    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(service, "execute_host", fake_execute)

    result = await get_registry().execute(
        "run_code", {"files": {"main.py": "print(1)"}},
        _ctx(permission_mode="readonly"),
    )
    assert result["ok"] is False
    assert result["business"] is True
    assert "切换到确认模式" in result["error"]
    assert "requires_approval" not in result
    assert called["host"] == 0


@pytest.mark.asyncio
async def test_server_readonly_run_command_stays_in_sandbox(monkeypatch, tmp_path):
    """Server readonly keeps executing read-only commands in the sanitized copy."""
    monkeypatch.setattr(settings, "nova_mode", "server")
    seen: dict = {}

    async def fake_get_repo(repo_id, user_id):
        return {"id": repo_id, "root_path": str(tmp_path)}

    async def fake_status():
        return {"available": True, "builder_available": False}

    async def fake_execute(files, command=None, **kwargs):
        seen.update(files=files, command=command, **kwargs)
        return {
            "stdout": "ok", "stderr": "", "exit_code": 0, "timed_out": False,
            "command": command,
        }

    monkeypatch.setattr("app.core.indexing.pipeline.get_repo", fake_get_repo)
    monkeypatch.setattr(run_command_tool, "sandbox_status", fake_status)
    monkeypatch.setattr(run_command_tool, "sandbox_execute", fake_execute)
    monkeypatch.setattr(run_command_tool, "check_sandbox_quota", AsyncMock())
    monkeypatch.setattr(run_command_tool, "log_audit", AsyncMock())

    result = await get_registry().execute(
        "run_command", {"command": "git status", "repo_id": REPO_ID},
        _ctx(permission_mode="readonly"),
    )
    assert result["ok"] is True
    assert seen["sanitized_workspace"] is True
    assert result["output"]["isolated"] is True
    assert "executor" not in result["output"]


@pytest.mark.asyncio
async def test_local_ask_run_command_approval_then_executes(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "nova_mode", "local")
    called = {"host": 0}

    async def fake_get_repo(repo_id, user_id):
        return {"id": repo_id, "root_path": str(tmp_path), "origin": "local"}

    async def fake_execute(command, **kwargs):
        called["host"] += 1
        return _host_result(command=command)

    monkeypatch.setattr("app.core.indexing.pipeline.get_repo", fake_get_repo)
    monkeypatch.setattr(service, "execute_host", fake_execute)
    ctx = _ctx(permission_mode="ask")

    denied = await get_registry().execute(
        "run_command", {"command": "git status", "repo_id": REPO_ID}, ctx
    )
    assert denied["ok"] is False
    assert denied["requires_approval"]["name"] == "run_command"
    assert called["host"] == 0

    ctx.approval_granted = True
    approved = await get_registry().execute(
        "run_command", {"command": "git status", "repo_id": REPO_ID}, ctx
    )
    assert approved["ok"] is True
    assert approved["output"]["executor"] == "host"
    assert called["host"] == 1


@pytest.mark.asyncio
async def test_server_ask_run_code_is_not_locally_gated(monkeypatch):
    """C1: server-mode ask behavior is unchanged."""
    monkeypatch.setattr(settings, "nova_mode", "server")

    async def available():
        return {"available": True, "builder_available": True}

    async def fake_execute(files, command=None, stdin="", timeout=None, **kwargs):
        return {
            "stdout": "1", "stderr": "", "exit_code": 0, "timed_out": False,
            "sandboxed": True, "command": command or "python main.py",
        }

    monkeypatch.setattr(run_code_tool, "sandbox_status", available)
    monkeypatch.setattr(run_code_tool, "sandbox_execute", fake_execute)
    monkeypatch.setattr(run_code_tool, "check_sandbox_quota", AsyncMock())
    monkeypatch.setattr(run_code_tool, "log_audit", AsyncMock())

    result = await get_registry().execute(
        "run_code", {"files": {"main.py": "print(1)"}}, _ctx(permission_mode="ask")
    )
    assert result["ok"] is True
    assert "requires_approval" not in result


@pytest.mark.asyncio
async def test_run_code_host_writes_temp_and_cleans_it(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(settings, "nova_data_dir", str(tmp_path / "NovaData"))
    seen: dict = {}

    async def fake_execute(command, **kwargs):
        seen.update(command=command, **kwargs)
        assert (Path(kwargs["root"]) / "main.py").read_text(encoding="utf-8") == "print('x')"
        return _host_result(command=command, stdout="x")

    monkeypatch.setattr(service, "execute_host", fake_execute)
    result = await service.run_code_host(
        {"main.py": "print('x')"}, None, root=tmp_path, timeout=5
    )
    assert seen["command"] == "python main.py"
    assert seen["venv_root"] == tmp_path
    assert result["isolation"] == "none"
    assert result["warning"] == service.WARNING
    assert result["workspace"] == "temporary"
    assert list((tmp_path / "NovaData" / "tmp").iterdir()) == []


@pytest.mark.asyncio
async def test_run_code_host_rejects_multiline(monkeypatch, tmp_path):
    called = {"host": False}

    async def fail_execute(command, **kwargs):  # pragma: no cover - must not run
        called["host"] = True
        raise AssertionError("must not execute")

    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(settings, "nova_data_dir", str(tmp_path / "NovaData"))
    monkeypatch.setattr(service, "execute_host", fail_execute)
    with pytest.raises(ToolBusinessError) as exc:
        await service.run_code_host(
            {"main.py": "print(1)"}, "python main.py\necho x", root=tmp_path
        )
    assert "多行" in str(exc.value)
    assert called["host"] is False
    # Rejected before staging: no temp tree is even created.
    assert not (tmp_path / "NovaData" / "tmp").exists()


@pytest.mark.asyncio
async def test_run_code_host_cleans_temp_when_executor_raises(monkeypatch, tmp_path):
    async def boom(command, **kwargs):
        raise OSError("spawn failed")

    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(settings, "nova_data_dir", str(tmp_path / "NovaData"))
    monkeypatch.setattr(service, "execute_host", boom)
    with pytest.raises(ToolBusinessError):
        await service.run_code_host({"main.py": "print(1)"}, None, root=tmp_path)
    assert list((tmp_path / "NovaData" / "tmp").iterdir()) == []


@pytest.mark.asyncio
async def test_run_code_host_staging_errors_are_business_errors(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "nova_mode", "local")

    # Missing data root (NOVA_DATA_DIR unset) must not leak RuntimeError.
    monkeypatch.setattr(settings, "nova_data_dir", "")
    monkeypatch.setattr(settings, "local_tmp_dir", "")
    with pytest.raises(ToolBusinessError) as exc:
        await service.run_code_host({"main.py": "print(1)"}, None, root=tmp_path)
    assert "本地执行失败" in str(exc.value)

    # A file/directory staging conflict must map to a business error and
    # leave no half-written temp tree behind.
    monkeypatch.setattr(settings, "nova_data_dir", str(tmp_path / "NovaData"))
    with pytest.raises(ToolBusinessError) as exc:
        await service.run_code_host(
            {"sub": "file", "sub/main.py": "print(1)"}, None, root=tmp_path
        )
    assert "临时工作目录" in str(exc.value)
    assert list((tmp_path / "NovaData" / "tmp").iterdir()) == []


@pytest.mark.asyncio
async def test_run_command_host_clamps_timeouts(monkeypatch, tmp_path):
    seen: dict = {}

    async def fake_execute(command, **kwargs):
        seen.update(kwargs)
        return _host_result(command=command)

    monkeypatch.setattr(service, "execute_host", fake_execute)
    await service.run_command_host("echo ok", root=tmp_path, timeout=-5)
    assert seen["timeout"] == 1
    await service.run_command_host("echo ok", root=tmp_path, timeout=9999)
    assert seen["timeout"] == 300


@pytest.mark.asyncio
async def test_run_code_host_rejects_secret_and_traversal(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(settings, "nova_data_dir", str(tmp_path / "NovaData"))
    written: list[str] = []

    async def fake_execute(command, **kwargs):
        root = Path(kwargs["root"])
        written.extend(p.name for p in root.rglob("*"))
        return _host_result(command=command)

    monkeypatch.setattr(service, "execute_host", fake_execute)
    await service.run_code_host(
        {"../escape.py": "x", ".env": "SECRET=1", "safe.py": "print(1)"},
        "python safe.py", root=tmp_path, timeout=5,
    )
    assert "safe.py" in written
    assert "escape.py" not in written
    assert ".env" not in written


@pytest.mark.asyncio
async def test_local_loop_hides_bridge_tools(monkeypatch):
    """Step 6: local mode never advertises local_run_command/local_write_file."""
    from app.core.agent import loop as loop_mod
    from unittest.mock import AsyncMock

    seen: dict = {}

    class RecordingRegistry:
        def specs(self, **kwargs):
            seen.update(kwargs)
            return []

        def get(self, name):
            return None

        async def execute(self, name, args, ctx):
            return {"ok": True, "output": {}, "ms": 1}

    class FakeLLM:
        async def astream_with_tools(self, messages, tools):
            seen["tools"] = tools
            yield {"type": "content", "content": "你好"}
            yield {"type": "finish", "finish_reason": "stop"}

    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(loop_mod, "get_registry", lambda: RecordingRegistry())
    monkeypatch.setattr(loop_mod, "get_llm", AsyncMock(return_value=FakeLLM()))
    monkeypatch.setattr(loop_mod, "retrieve", AsyncMock(return_value=[]))
    monkeypatch.setattr(loop_mod.session_mod, "recent_messages", AsyncMock(return_value=[]))
    monkeypatch.setattr(loop_mod.session_mod, "add_message", AsyncMock(return_value=101))
    monkeypatch.setattr(loop_mod.facts_mod, "get_relevant_facts", AsyncMock(return_value=[]))
    monkeypatch.setattr(loop_mod.facts_mod, "extract_facts_from_turn", AsyncMock(return_value=0))
    monkeypatch.setattr(loop_mod, "log_audit", AsyncMock())
    monkeypatch.setattr(loop_mod, "_record_usage", AsyncMock())

    user = {"id": 1, "username": "local", "role": "local"}
    session = {"id": "s-1", "title": "t", "permission_mode": "auto", "model": ""}
    events = []
    async for event in loop_mod.run_chat(user, session, "hi", []):
        events.append(event)
    assert seen["local_available"] is False


@pytest.mark.asyncio
async def test_run_code_host_tool_layer_never_passes_model_env(monkeypatch, tmp_path):
    """Requirement 4: tool args (env/stdin) never reach execute_host's env."""
    from app.core.tools import run_code as run_code_tool

    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(settings, "nova_data_dir", str(tmp_path / "NovaData"))
    seen: dict = {}

    async def fake_execute(command, **kwargs):
        seen.update(command=command, **kwargs)
        return _host_result(command=command)

    monkeypatch.setattr(service, "execute_host", fake_execute)
    result = await run_code_tool.run_code(
        {
            "files": {"main.py": "print(1)"},
            "env": "node",
            "stdin": "EVIL_KEY=x",
            "command": "python main.py",
        },
        _ctx(),
    )
    assert seen["env"] is None
    assert result["executor"] == "host"
    assert result["isolation"] == "none"
    assert result["warning"]
    assert result["workspace"] == "temporary"
    assert result["stdin_ignored"] is True
    assert "stdin" in result["hint"]


@pytest.mark.asyncio
async def test_run_code_local_missing_data_dir_is_business_error(monkeypatch):
    """Unset NOVA_DATA_DIR must surface as a Chinese business error."""
    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(settings, "nova_data_dir", "")
    monkeypatch.setattr(settings, "local_tmp_dir", "")
    with pytest.raises(ToolBusinessError) as exc:
        await run_code_tool.run_code({"files": {"main.py": "print(1)"}}, _ctx())
    assert "NOVA_DATA_DIR" in str(exc.value)
    assert "repo_id" in str(exc.value)


def test_local_tool_descriptions_warn_no_isolation(monkeypatch):
    monkeypatch.setattr(settings, "nova_mode", "local")

    command_desc = run_command_tool.tool_description()
    assert "无容器隔离" in command_desc
    assert "当前 Windows 用户权限" in command_desc
    assert "主机网络" in command_desc
    assert "后台" in command_desc and "job_id" in command_desc
    assert "隔离容器内" not in command_desc

    code_desc = run_code_tool.tool_description()
    assert "无容器隔离" in code_desc
    assert "当前 Windows 用户权限" in code_desc
    assert "stdin" in code_desc
    assert "隔离沙箱中" not in code_desc

    monkeypatch.setattr(settings, "nova_mode", "server")
    assert "隔离容器内" in run_command_tool.tool_description()
    assert "隔离沙箱中" in run_code_tool.tool_description()


def test_local_tool_parameters_are_local_aware(monkeypatch):
    monkeypatch.setattr(settings, "nova_mode", "local")

    command_props = run_command_tool.tool_parameters()["properties"]
    assert "项目根目录" in command_props["command"]["description"]
    assert "当前 Windows 用户" in command_props["command"]["description"]
    assert "不支持自定义镜像" in command_props["env"]["description"]
    assert "主机当前用户" in command_props["env"]["description"]

    code_props = run_code_tool.tool_parameters()["properties"]
    assert "沙箱" not in code_props["files"]["description"]
    assert "主机临时目录" in code_props["files"]["description"]
    assert "沙箱" not in code_props["repo_id"]["description"]
    assert "不支持自定义镜像" in code_props["env"]["description"]
    assert "主机当前用户" in code_props["env"]["description"]

    monkeypatch.setattr(settings, "nova_mode", "server")
    server_code = run_code_tool.tool_parameters()["properties"]
    assert "沙箱" in server_code["files"]["description"]
    assert "运行环境镜像" in run_command_tool.tool_parameters()["properties"]["env"]["description"]


@pytest.mark.asyncio
async def test_run_argv_host_marks_no_isolation(monkeypatch, tmp_path):
    seen: dict = {}

    async def fake_execute(argv, **kwargs):
        seen.update(argv=argv, **kwargs)
        return _host_result(command=" ".join(argv))

    monkeypatch.setattr(service, "execute_argv_host", fake_execute)
    result = await service.run_argv_host(
        ["ruff", "check", "."], root=tmp_path, timeout=999,
        job_id="tool-3", user_id=7,
    )
    assert seen["argv"] == ["ruff", "check", "."]
    assert seen["timeout"] == 300
    assert seen["job_id"] == "tool-3"
    assert seen["user_id"] == 7
    assert result["warning"] == service.WARNING


@pytest.mark.asyncio
async def test_run_argv_host_maps_executor_errors(monkeypatch, tmp_path):
    async def fail_execute(argv, **kwargs):
        raise OSError("spawn failed")

    monkeypatch.setattr(service, "execute_argv_host", fail_execute)
    with pytest.raises(ToolBusinessError):
        await service.run_argv_host(["ruff", "--version"], root=tmp_path, timeout=5)

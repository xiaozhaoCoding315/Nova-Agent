"""Host executor wiring: local run_command / run_code, status and cancel.

Server-mode behavior is untouched: every local branch is behind
``settings.use_host_executor`` and the policy gate still runs inside
``ToolRegistry.execute`` before any host execution.
"""
import sys
from pathlib import Path

import pytest

from app.config import settings
from app.core.exec import service
from app.core.sandbox import runtime as sandbox_runtime
from app.core.tools import get_registry
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
    assert "无容器隔离" in result["warning"]


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
    assert result["isolation"] == "none"
    assert list((tmp_path / "NovaData" / "tmp").iterdir()) == []


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

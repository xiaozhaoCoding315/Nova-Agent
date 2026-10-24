"""local_run_command 工具与本地执行器接口（表交互均 mock）。"""
from unittest.mock import AsyncMock

import pytest

from app.core.tools import local_exec as mod
from app.core.tools.base import ToolBusinessError, ToolContext


def _ctx() -> ToolContext:
    return ToolContext(user={"id": 7, "role": "demo"}, permission_mode="auto")


def test_tool_registered_with_proc_exec_capability():
    from app.core.tools import build_registry
    registry = build_registry()
    spec = next((t for t in registry.specs() if t.get("function", {}).get("name") == "local_run_command"), None)
    assert spec is not None
    assert spec["function"]["description"]


@pytest.mark.asyncio
async def test_local_run_command_returns_result_when_agent_replies(monkeypatch):
    states = iter([
        [("pending", None, None)],
        [("done", "build ok", 0)],
    ])

    async def fake_query(_sql, params):
        return next(states)

    captured: dict = {}

    async def fake_execute(_sql, params):
        captured["insert"] = params
        return []

    monkeypatch.setattr(mod, "query", fake_query)
    monkeypatch.setattr(mod, "execute", fake_execute)
    monkeypatch.setattr(mod.asyncio, "sleep", AsyncMock())

    result = await mod.local_run_command({"command": "npm run build", "cwd": "web"}, _ctx())

    assert result["exit_code"] == 0
    assert result["executed_on"] == "user-local-machine"
    assert "build ok" in result["stdout"]
    assert captured["insert"][1] == 7


@pytest.mark.asyncio
async def test_local_run_command_surfaces_error_result(monkeypatch):
    states = iter([[("error", "command not found: npm", 127)]])

    async def fake_query(_sql, params):
        return next(states)

    monkeypatch.setattr(mod, "query", fake_query)
    monkeypatch.setattr(mod, "execute", AsyncMock(return_value=[]))
    monkeypatch.setattr(mod.asyncio, "sleep", AsyncMock())

    result = await mod.local_run_command({"command": "npm run build"}, _ctx())
    assert result["exit_code"] == 127
    assert "npm" in result["stderr"]


@pytest.mark.asyncio
async def test_local_run_command_times_out_without_agent(monkeypatch):
    async def fake_query(_sql, params):
        return [("pending", None, None)]

    monkeypatch.setattr(mod, "query", fake_query)
    monkeypatch.setattr(mod, "execute", AsyncMock(return_value=[]))
    monkeypatch.setattr(mod.asyncio, "sleep", AsyncMock())
    monkeypatch.setattr(mod.settings, "local_exec_timeout", 0)

    with pytest.raises(ToolBusinessError, match="本地执行器"):
        await mod.local_run_command({"command": "ls"}, _ctx())


@pytest.mark.asyncio
async def test_claim_pending_marks_rows_claimed(monkeypatch):
    from app.api.v1 import local_exec as api_mod

    async def fake_execute(_sql, params):
        assert params == (7,)
        return [("req-1", ".", "git status", "shell", None, None)]

    monkeypatch.setattr(api_mod, "execute", fake_execute)
    claims = await api_mod.claim_pending(user={"id": 7})
    assert len(claims) == 1
    assert claims[0].id == "req-1"
    assert claims[0].command == "git status"


@pytest.mark.asyncio
async def test_submit_result_rejects_foreign_request(monkeypatch):
    from app.api.v1 import local_exec as api_mod

    monkeypatch.setattr(api_mod, "execute", AsyncMock(return_value=[]))
    with pytest.raises(Exception):
        await api_mod.submit_result(
            "3f2b8c1e-1234-5678-9abc-def012345678",
            api_mod.LocalExecResult(ok=True, output="done", exit_code=0),
            user={"id": 7},
        )


@pytest.mark.asyncio
async def test_local_write_file_dispatches_write(monkeypatch):
    captured: dict = {}

    async def fake_execute(_sql, params):
        captured["insert"] = params
        return []

    states = iter([[("done", "written 11 bytes -> x", 0)]])

    async def fake_query(_sql, params):
        return next(states)

    monkeypatch.setattr(mod, "query", fake_query)
    monkeypatch.setattr(mod, "execute", fake_execute)
    monkeypatch.setattr(mod.asyncio, "sleep", AsyncMock())

    result = await mod.local_write_file(
        {"path": "output/main.py", "content": "print('hi')\n"}, _ctx()
    )
    assert result["exit_code"] == 0
    assert result["path"] == "output/main.py"
    assert captured["insert"][4] == "write"
    assert captured["insert"][5] == "output/main.py"


@pytest.mark.asyncio
async def test_local_write_file_rejects_escape_paths(_ctx=_ctx):
    with pytest.raises(ToolBusinessError):
        await mod.local_write_file({"path": "../evil.py", "content": "x"}, _ctx())
    with pytest.raises(ToolBusinessError):
        await mod.local_write_file({"path": "/etc/passwd", "content": "x"}, _ctx())
    with pytest.raises(ToolBusinessError):
        await mod.local_write_file({"path": "ok.py"}, _ctx())


@pytest.mark.asyncio
async def test_status_reflects_agent_heartbeat(monkeypatch):
    from app.api.v1 import local_exec as api_mod

    api_mod._AGENT_LAST_SEEN.pop(7, None)
    user = {"id": 7}
    offline = await api_mod.local_exec_status(user=user)
    assert offline["connected"] is False

    async def fake_execute(_sql, params):
        return []

    monkeypatch.setattr(api_mod, "execute", fake_execute)
    await api_mod.claim_pending(user=user)
    online = await api_mod.local_exec_status(user=user)
    assert online["connected"] is True

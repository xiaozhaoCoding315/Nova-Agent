"""Pre/post tool hooks are operator-controlled and fail closed."""
import sys
from unittest.mock import AsyncMock

import pytest

from app.config import settings
from app.core.tools import base as tools_base
from app.core.tools.base import ToolContext, ToolDefinition, ToolRegistry


def _make_registry(func):
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="probe", description="", parameters={}, func=func,
        category="read", capabilities=["fs.read"],
    ))
    return registry


def _script(path, body: str) -> str:
    path.write_text(body, encoding="utf-8")
    return f'"{sys.executable}" "{path}"'


@pytest.mark.asyncio
async def test_pre_hook_exit_2_blocks_tool(monkeypatch, tmp_path):
    monkeypatch.setattr(tools_base, "log_audit", AsyncMock())
    script = _script(
        tmp_path / "pre.py",
        "import json,sys\n"
        "payload=json.load(sys.stdin)\n"
        "open('hook_payload.json','w').write(json.dumps(payload))\n"
        "print('blocked by test hook', file=sys.stderr)\n"
        "sys.exit(2)\n",
    )
    monkeypatch.setattr(settings, "tool_pre_hook", script)
    func = AsyncMock(return_value={"ok": True})
    registry = _make_registry(func)
    ctx = ToolContext(user={"id": 1, "role": "admin"}, repo_roots={"r": str(tmp_path)})

    result = await registry.execute("probe", {}, ctx)

    assert result["ok"] is False and result["business"] is True
    assert "前置钩子" in result["error"]
    assert func.await_count == 0
    assert "probe" in (tmp_path / "hook_payload.json").read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_missing_pre_hook_fails_closed(monkeypatch):
    monkeypatch.setattr(tools_base, "log_audit", AsyncMock())
    monkeypatch.setattr(settings, "tool_pre_hook", "nova-command-that-does-not-exist")
    func = AsyncMock(return_value={"ok": True})
    registry = _make_registry(func)

    result = await registry.execute(
        "probe", {}, ToolContext(user={"id": 1, "role": "admin"})
    )

    assert result["ok"] is False
    assert "不存在" in result["error"]
    assert func.await_count == 0


@pytest.mark.asyncio
async def test_post_hook_failure_does_not_change_result(monkeypatch, tmp_path):
    monkeypatch.setattr(tools_base, "log_audit", AsyncMock())
    script = _script(
        tmp_path / "post.py",
        "import sys\nopen('post_ran.txt','w').write('yes')\nsys.exit(1)\n",
    )
    monkeypatch.setattr(settings, "tool_pre_hook", "")
    monkeypatch.setattr(settings, "tool_post_hook", script)
    func = AsyncMock(return_value={"ok": True})
    registry = _make_registry(func)
    ctx = ToolContext(user={"id": 1, "role": "admin"}, repo_roots={"r": str(tmp_path)})

    result = await registry.execute("probe", {}, ctx)

    assert result["ok"] is True
    assert func.await_count == 1
    assert (tmp_path / "post_ran.txt").exists()

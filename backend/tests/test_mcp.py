"""MCP config, allowlist, tool registration and capability enforcement."""
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.config import settings
from app.core.mcp.manager import MCPManager
from app.core.tools import base as tools_base
from app.core.tools.base import ToolContext, ToolRegistry

SERVER_SCRIPT = Path(__file__).with_name("mcp_fake_server.py")


def _config(allow_tools=None, capabilities=None):
    return {
        "servers": [{
            "name": "demo",
            "command": sys.executable,
            "args": [str(SERVER_SCRIPT)],
            "allow_tools": allow_tools or ["echo"],
            "capabilities": capabilities or {"echo": ["fs.read"]},
            "enabled": True,
            "timeout": 10,
        }]
    }


@pytest.fixture(autouse=True)
def mcp_settings(monkeypatch):
    monkeypatch.setattr(settings, "mcp_enabled", True)
    monkeypatch.setattr(settings, "mcp_admin_only", True)
    monkeypatch.setattr(settings, "mcp_timeout", 10)


@pytest.mark.asyncio
async def test_manager_discovers_allowlisted_tool_and_calls_it(monkeypatch):
    monkeypatch.setattr(settings, "mcp_servers_json", json.dumps(_config()))
    monkeypatch.setattr(tools_base, "log_audit", AsyncMock())
    manager = MCPManager()
    await manager.start()
    try:
        definitions = manager.tool_definitions()
        names = [tool.name for tool in definitions]
        assert names == ["mcp__demo__echo"]

        registry = ToolRegistry()
        for tool in definitions:
            registry.register(tool)
        ctx = ToolContext(user={"id": 1, "role": "admin"}, permission_mode="auto")
        result = await registry.execute("mcp__demo__echo", {"text": "hello"}, ctx)

        assert result["ok"] is True
        assert result["output"]["text"] == "echo: hello"
        assert set(result["output"]["content"][0]) == {"type", "text"}
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_mcp_tools_are_admin_only(monkeypatch):
    monkeypatch.setattr(settings, "mcp_servers_json", json.dumps(_config()))
    monkeypatch.setattr(tools_base, "log_audit", AsyncMock())
    manager = MCPManager()
    await manager.start()
    try:
        registry = ToolRegistry()
        for tool in manager.tool_definitions():
            registry.register(tool)
        ctx = ToolContext(user={"id": 2, "role": "demo"}, permission_mode="auto")
        result = await registry.execute("mcp__demo__echo", {"text": "hello"}, ctx)
        assert result["ok"] is False and result["business"] is True
        assert "管理员" in result["error"]
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_server_opt_in_opens_mcp_to_regular_users(monkeypatch):
    """`admin_only: false` on one server overrides the global admin-only default."""
    config = _config()
    config["servers"][0]["admin_only"] = False
    monkeypatch.setattr(settings, "mcp_servers_json", json.dumps(config))
    monkeypatch.setattr(tools_base, "log_audit", AsyncMock())
    manager = MCPManager()
    await manager.start()
    try:
        registry = ToolRegistry()
        for tool in manager.tool_definitions():
            registry.register(tool)
        ctx = ToolContext(user={"id": 2, "role": "demo"}, permission_mode="auto")
        result = await registry.execute("mcp__demo__echo", {"text": "hi"}, ctx)
        assert result["ok"] is True
        assert result["output"]["text"] == "echo: hi"
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_secrets_capability_stays_admin_only_even_when_open(monkeypatch):
    config = _config(capabilities={"echo": ["secrets.read"]})
    config["servers"][0]["admin_only"] = False
    monkeypatch.setattr(settings, "mcp_servers_json", json.dumps(config))
    monkeypatch.setattr(tools_base, "log_audit", AsyncMock())
    manager = MCPManager()
    await manager.start()
    try:
        registry = ToolRegistry()
        for tool in manager.tool_definitions():
            registry.register(tool)
        ctx = ToolContext(user={"id": 2, "role": "demo"}, permission_mode="auto")
        result = await registry.execute("mcp__demo__echo", {"text": "hi"}, ctx)
        assert result["ok"] is False and result["business"] is True
        # Either the policy engine (secrets are blanket-denied) or the manager
        # closure stops it; both mean the capability never reaches users.
        assert "密钥" in result["error"] or "敏感凭据" in result["error"]
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_non_allowlisted_tool_is_not_exposed(monkeypatch):
    monkeypatch.setattr(
        settings, "mcp_servers_json",
        json.dumps(_config(allow_tools=["echo"], capabilities={"echo": ["fs.read"]})),
    )
    manager = MCPManager()
    await manager.start()
    try:
        assert manager.tool_names() == ["mcp__demo__echo"]
        assert "mcp__demo__write_secret" not in manager.tool_names()
    finally:
        await manager.stop()

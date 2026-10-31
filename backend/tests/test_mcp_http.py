"""MCP streamable HTTP transport and config parsing."""
import json

import httpx
import pytest

from app.config import settings
from app.core.mcp import config as mcp_config
from app.core.mcp.http_client import MCPHttpClient


def _handler(request: httpx.Request) -> httpx.Response:
    payload = json.loads(request.content)
    method = payload.get("method")
    if method == "initialize":
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": payload["id"], "result": {"protocolVersion": "2025-03-26"}},
            headers={"mcp-session-id": "session-1"},
        )
    if method == "notifications/initialized":
        return httpx.Response(202)
    if method == "tools/list":
        assert request.headers.get("mcp-session-id") == "session-1"
        return httpx.Response(200, json={
            "jsonrpc": "2.0", "id": payload["id"],
            "result": {"tools": [{"name": "echo", "description": "echo", "inputSchema": {}}]},
        })
    if method == "tools/call":
        body = {"jsonrpc": "2.0", "id": payload["id"], "result": {"content": [{"type": "text", "text": "hi"}]}}
        return httpx.Response(
            200,
            content=f"event: message\ndata: {json.dumps(body)}\n\n",
            headers={"content-type": "text/event-stream"},
        )
    return httpx.Response(404)


@pytest.mark.asyncio
async def test_http_client_json_and_sse():
    client = MCPHttpClient(
        "https://mcp.example.com/mcp", headers={"Authorization": "Bearer test"},
        transport=httpx.MockTransport(_handler),
    )
    await client.start()
    try:
        tools = await client.list_tools()
        assert tools[0]["name"] == "echo"
        result = await client.call_tool("echo", {"text": "hi"})
        assert result["content"][0]["text"] == "hi"
    finally:
        await client.aclose()


def test_http_server_config(monkeypatch):
    monkeypatch.setattr(settings, "mcp_enabled", True)
    monkeypatch.setattr(settings, "mcp_servers_json", json.dumps({"servers": [{
        "name": "remote",
        "transport": "http",
        "url": "https://mcp.example.com/mcp",
        "headers": {"Authorization": "Bearer test"},
        "capabilities": {"echo": ["fs.read"]},
        "allow_tools": ["echo"],
    }]}))

    configs = mcp_config.load_server_configs()
    assert len(configs) == 1
    assert configs[0].transport == "http"
    assert configs[0].url == "https://mcp.example.com/mcp"
    assert configs[0].headers["Authorization"] == "Bearer test"


def test_http_config_rejects_plain_http_public_host(monkeypatch):
    monkeypatch.setattr(settings, "mcp_enabled", True)
    monkeypatch.setattr(settings, "mcp_servers_json", json.dumps({"servers": [{
        "name": "insecure",
        "transport": "http",
        "url": "http://mcp.example.com/mcp",
        "capabilities": {"echo": ["fs.read"]},
        "allow_tools": ["echo"],
    }]}))
    assert mcp_config.load_server_configs() == []

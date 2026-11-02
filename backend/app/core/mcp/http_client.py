"""MCP streamable HTTP transport (JSON or SSE responses).

Supports authenticated HTTP MCP servers without spawning a local process.
Session ids returned by ``initialize`` are echoed on subsequent requests.
"""
import json

import httpx
import structlog

from app.core.mcp.client import MCPError

logger = structlog.get_logger()

PROTOCOL_VERSION = "2025-03-26"


class MCPHttpClient:
    def __init__(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: int = 30,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.url = url
        self.timeout = timeout
        self.headers = dict(headers or {})
        self._transport = transport
        self._client: httpx.AsyncClient | None = None
        self._session_id = ""
        self._next_id = 0

    async def start(self) -> dict:
        self._client = httpx.AsyncClient(
            timeout=self.timeout, transport=self._transport, follow_redirects=False,
        )
        result = await self.request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "nova-agent", "version": "2.1.1"},
        }, timeout=15)
        await self.notify("notifications/initialized", {})
        return result

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _headers(self) -> dict:
        headers = {
            **self.headers,
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
            headers["MCP-Protocol-Version"] = PROTOCOL_VERSION
        return headers

    async def _post(self, payload: dict) -> list[dict]:
        if self._client is None:
            raise MCPError("MCP HTTP client 未启动")
        try:
            response = await self._client.post(
                self.url, json=payload, headers=self._headers()
            )
        except httpx.HTTPError as exc:
            raise MCPError(f"MCP HTTP 请求失败：{exc}") from exc

        session = response.headers.get("mcp-session-id")
        if session:
            self._session_id = session
        if response.status_code >= 400:
            raise MCPError(
                f"MCP HTTP {response.status_code}: {response.text[:500]}"
            )
        if response.status_code == 202 or not response.content:
            return []

        content_type = response.headers.get("content-type", "")
        if "text/event-stream" in content_type:
            messages: list[dict] = []
            for line in response.text.splitlines():
                if not line.startswith("data:"):
                    continue
                raw = line[5:].strip()
                if raw:
                    try:
                        messages.append(json.loads(raw))
                    except json.JSONDecodeError:
                        logger.warning("mcp_http_bad_sse", line=raw[:300])
            return messages
        try:
            data = response.json()
        except ValueError as exc:
            raise MCPError("MCP HTTP 返回了非 JSON 内容") from exc
        return [data] if isinstance(data, dict) else []

    async def notify(self, method: str, params: dict | None = None) -> None:
        await self._post({"jsonrpc": "2.0", "method": method, "params": params or {}})

    async def request(
        self, method: str, params: dict | None = None, timeout: int | None = None
    ) -> dict:
        self._next_id += 1
        request_id = self._next_id
        messages = await self._post({
            "jsonrpc": "2.0", "id": request_id, "method": method,
            "params": params or {},
        })
        for message in messages:
            if message.get("id") != request_id:
                continue
            if "error" in message:
                error = message["error"]
                raise MCPError(str(error.get("message") or error))
            return message.get("result") or {}
        raise MCPError(f"MCP HTTP 响应缺少 id={request_id}")

    async def list_tools(self) -> list[dict]:
        result = await self.request("tools/list", {}, timeout=self.timeout)
        tools = result.get("tools") if isinstance(result, dict) else None
        return [tool for tool in tools or [] if isinstance(tool, dict)]

    async def call_tool(self, name: str, arguments: dict) -> dict:
        result = await self.request(
            "tools/call", {"name": name, "arguments": arguments},
            timeout=self.timeout,
        )
        return result if isinstance(result, dict) else {"content": result}

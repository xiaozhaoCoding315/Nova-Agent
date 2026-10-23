"""MCP server manager: start clients, discover allowlisted tools, expose them."""
from dataclasses import dataclass

import structlog

from app.config import settings
from app.core.mcp.client import MCPClient, MCPError, _safe_name
from app.core.mcp.config import load_server_configs
from app.core.tools.base import ToolBusinessError, ToolDefinition

logger = structlog.get_logger()


@dataclass(frozen=True)
class MCPToolInfo:
    server: str
    name: str
    exposed_name: str
    description: str
    schema: dict
    capabilities: list[str]
    admin_only: bool


class MCPManager:
    def __init__(self) -> None:
        self._clients: dict[str, MCPClient] = {}
        self._tools: list[MCPToolInfo] = []
        self._started = False

    @property
    def started(self) -> bool:
        return self._started

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        configs = load_server_configs()
        if not configs:
            logger.info("mcp_no_servers")
            return

        for config in configs:
            client = MCPClient(config.command, list(config.args), timeout=config.timeout)
            try:
                await client.start()
                tools = await client.list_tools()
            except Exception as exc:  # noqa: BLE001
                logger.warning("mcp_server_start_failed", server=config.name, error=str(exc))
                await client.aclose()
                continue

            discovered = {str(tool.get("name")): tool for tool in tools}
            allowed = 0
            for tool_name, caps in config.allow_tools.items():
                tool = discovered.get(tool_name)
                if not tool:
                    logger.warning(
                        "mcp_tool_not_found", server=config.name, tool=tool_name
                    )
                    continue
                schema = tool.get("inputSchema")
                if not isinstance(schema, dict):
                    schema = {"type": "object", "properties": {}}
                exposed = f"mcp__{_safe_name(config.name)}__{_safe_name(tool_name)}"
                if any(info.exposed_name == exposed for info in self._tools):
                    logger.warning("mcp_tool_name_collision", name=exposed)
                    continue
                self._tools.append(MCPToolInfo(
                    server=config.name,
                    name=tool_name,
                    exposed_name=exposed,
                    description=str(tool.get("description") or f"MCP tool {tool_name}")[:1000],
                    schema=schema,
                    capabilities=list(caps),
                    admin_only=config.admin_only,
                ))
                allowed += 1

            if allowed:
                self._clients[config.name] = client
                logger.info(
                    "mcp_server_ready", server=config.name, tools=allowed
                )
            else:
                logger.info("mcp_server_no_allowed_tools", server=config.name)
                await client.aclose()

    async def stop(self) -> None:
        for client in self._clients.values():
            await client.aclose()
        self._clients.clear()
        self._tools.clear()
        self._started = False

    async def call(self, server: str, tool: str, arguments: dict) -> dict:
        client = self._clients.get(server)
        if not client:
            raise MCPError(f"MCP server 未运行：{server}")
        return await client.call_tool(tool, arguments)

    def tool_definitions(self) -> list[ToolDefinition]:
        definitions: list[ToolDefinition] = []
        for info in self._tools:
            async def _call(args: dict, ctx, _info: MCPToolInfo = info) -> dict:
                if (settings.mcp_admin_only or _info.admin_only) and \
                        (ctx.user or {}).get("role") != "admin":
                    raise ToolBusinessError("MCP 工具仅管理员可用")
                try:
                    result = await self.call(_info.server, _info.name, args)
                except MCPError as exc:
                    raise ToolBusinessError(str(exc)) from exc
                if result.get("is_error"):
                    raise ToolBusinessError(result.get("text") or "MCP 工具返回错误")
                return result

            definitions.append(ToolDefinition(
                name=info.exposed_name,
                description=f"[MCP:{info.server}] {info.description}",
                parameters=info.schema,
                func=_call,
                category="execute",
                capabilities=info.capabilities,
                timeout=settings.mcp_timeout,
            ))
        return definitions

    def tool_names(self) -> list[str]:
        return [info.exposed_name for info in self._tools]


manager = MCPManager()

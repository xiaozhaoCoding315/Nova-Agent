"""MCP server configuration (operator-controlled allowlist)."""
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)

KNOWN_CAPABILITIES = {
    "fs.read", "fs.write", "proc.exec", "net.fetch",
    "git.write", "deploy", "secrets.read",
}


@dataclass(frozen=True)
class MCPServerConfig:
    name: str
    command: str
    args: tuple[str, ...]
    allow_tools: dict[str, list[str]] = field(default_factory=dict)
    admin_only: bool = False
    timeout: int = 30


def _load_raw() -> object:
    if settings.mcp_servers_json.strip():
        return json.loads(settings.mcp_servers_json)
    path = Path(settings.mcp_config_path)
    if not path.is_absolute():
        path = Path.cwd() / path
    if not path.is_file():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def load_server_configs() -> list[MCPServerConfig]:
    if not settings.mcp_enabled:
        return []
    try:
        data = _load_raw()
    except Exception as exc:  # noqa: BLE001
        logger.warning("mcp_config_invalid: %s", exc)
        return []
    servers = data.get("servers") if isinstance(data, dict) else data
    if not isinstance(servers, list):
        return []

    configs: list[MCPServerConfig] = []
    seen: set[str] = set()
    for raw in servers:
        if not isinstance(raw, dict) or raw.get("enabled", True) is False:
            continue
        name = str(raw.get("name") or "").strip()
        command = str(raw.get("command") or "").strip()
        if not name or not command or name in seen:
            logger.warning("mcp_server_skipped: %s", name or "<unnamed>")
            continue
        args = raw.get("args") or []
        if not isinstance(args, list) or not all(isinstance(item, str) for item in args):
            logger.warning("mcp_server_args_invalid: %s", name)
            continue
        raw_caps = raw.get("capabilities") if isinstance(raw.get("capabilities"), dict) else {}
        allow: dict[str, list[str]] = {}
        for tool, caps in raw_caps.items():
            if not isinstance(caps, list):
                continue
            normalized = [str(cap) for cap in caps if str(cap) in KNOWN_CAPABILITIES]
            if normalized:
                allow[str(tool)] = normalized
        allowed_tools = raw.get("allow_tools")
        if isinstance(allowed_tools, list) and allowed_tools:
            allow = {tool: caps for tool, caps in allow.items() if tool in set(map(str, allowed_tools))}
        if not allow:
            logger.warning("mcp_server_no_allowed_tools: %s", name)
            continue
        seen.add(name)
        configs.append(MCPServerConfig(
            name=name, command=command, args=tuple(args), allow_tools=allow,
            admin_only=bool(raw.get("admin_only", False)),
            timeout=int(raw.get("timeout") or settings.mcp_timeout),
        ))
    return configs

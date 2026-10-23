"""Tool package: registry singleton with all built-in tools registered."""
from app.config import settings
from app.core.tools import diagnose, fetch_url, json_tool, run_code, search_code, sql_tool
from app.core.tools.base import (  # noqa: F401  (re-exported for callers)
    ToolBusinessError,
    ToolContext,
    ToolDefinition,
    ToolRegistry,
)


def build_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(run_code.TOOL)
    registry.register(diagnose.TOOL)
    registry.register(search_code.TOOL)
    registry.register(json_tool.TOOL)
    registry.register(sql_tool.TOOL)
    if settings.enable_fetch_url:
        registry.register(fetch_url.TOOL)
    return registry


_registry: ToolRegistry | None = None


def get_registry() -> ToolRegistry:
    global _registry
    if _registry is None:
        _registry = build_registry()
    return _registry
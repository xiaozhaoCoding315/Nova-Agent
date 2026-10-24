"""Tool package: registry singleton with all built-in tools registered."""
from app.config import settings
from app.core.tools import (
    diagnose, fetch_url, impact, install_deps, json_tool, list_files, read_attachment,
    read_file, run_code, search_code, sql_tool, write_files,
)
from app.core.tools.base import (  # noqa: F401  (re-exported for callers)
    ToolBusinessError,
    ToolContext,
    ToolDefinition,
    ToolRegistry,
)


def build_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(run_code.TOOL)
    registry.register(read_file.TOOL)
    registry.register(list_files.TOOL)
    registry.register(read_attachment.TOOL)
    registry.register(search_code.TOOL)
    registry.register(impact.TOOL)
    registry.register(diagnose.TOOL)
    registry.register(write_files.TOOL)
    registry.register(install_deps.TOOL)
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
"""Agent Skill tool package — registers built-in skills on import."""
from app.core.tools.base import (  # noqa: F401
    Tool,
    ToolError,
    ToolRegistry,
    registry,
    run_tool,
    validate_arguments,
)
from app.core.tools.calculator import calculator_tool
from app.core.tools.db_query import db_query_tool
from app.core.tools.doc_parser import doc_parser_tool

registry.register(calculator_tool)
registry.register(db_query_tool)
registry.register(doc_parser_tool)

__all__ = [
    "Tool",
    "ToolError",
    "ToolRegistry",
    "registry",
    "run_tool",
    "validate_arguments",
    "calculator_tool",
    "db_query_tool",
    "doc_parser_tool",
]

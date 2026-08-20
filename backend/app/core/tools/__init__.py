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
from app.core.tools.code_executor import code_executor_tool
from app.core.tools.db_query import db_query_tool
from app.core.tools.doc_parser import doc_parser_tool
from app.core.tools.error_diagnosis import error_diagnosis_tool
from app.core.tools.json_tool import json_tool

registry.register(calculator_tool)
registry.register(code_executor_tool)
registry.register(db_query_tool)
registry.register(doc_parser_tool)
registry.register(error_diagnosis_tool)
registry.register(json_tool)

__all__ = [
    "Tool",
    "ToolError",
    "ToolRegistry",
    "registry",
    "run_tool",
    "validate_arguments",
    "calculator_tool",
    "code_executor_tool",
    "db_query_tool",
    "doc_parser_tool",
    "error_diagnosis_tool",
    "json_tool",
]

"""Unit tests for the Agent Skill tool framework."""
import json

import pytest

from app.core.tools import registry, run_tool, Tool, ToolError
from app.core.tools.base import validate_arguments
from app.core.tools.calculator import safe_eval
from app.core.tools.db_query import _validate_sql, _force_limit, _FORBIDDEN_KEYWORDS


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def test_registry_has_builtin_tools():
    names = registry.names()
    assert "calculator" in names
    assert "db_query" in names
    assert "doc_parser" in names


def test_registry_openai_spec_format():
    tools = registry.to_openai_tools()
    assert isinstance(tools, list) and len(tools) >= 3
    for spec in tools:
        assert spec["type"] == "function"
        fn = spec["function"]
        assert fn["name"] and fn["description"]
        assert isinstance(fn["parameters"], dict)


def test_registry_duplicate_rejected():
    from app.core.tools.base import ToolRegistry
    reg = ToolRegistry()
    tool = Tool(name="t", description="d", parameters={"type": "object", "properties": {}},
                handler=None)
    reg.register(tool)
    with pytest.raises(ToolError):
        reg.register(tool)


def test_registry_unknown_tool():
    with pytest.raises(ToolError):
        registry.get("no_such_tool")


# ---------------------------------------------------------------------------
# Argument validation
# ---------------------------------------------------------------------------

def _calc_tool():
    return registry.get("calculator")


def test_validate_arguments_accepts_dict_and_json_string():
    tool = _calc_tool()
    assert validate_arguments(tool, '{"expression": "1+1"}') == {"expression": "1+1"}
    assert validate_arguments(tool, {"expression": "1+1"}) == {"expression": "1+1"}


def test_validate_arguments_rejects_bad_json_and_missing_field():
    tool = _calc_tool()
    with pytest.raises(ToolError):
        validate_arguments(tool, "{not json")
    with pytest.raises(ToolError):
        validate_arguments(tool, {})


# ---------------------------------------------------------------------------
# run_tool contract: never raises, always returns dict
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_tool_unknown_returns_error_dict():
    result = await run_tool("ghost_tool", "{}")
    assert result["ok"] is False
    assert "unknown tool" in result["error"]


@pytest.mark.asyncio
async def test_run_tool_bad_arguments_returns_error_dict():
    result = await run_tool("calculator", "{broken json")
    assert result["ok"] is False
    assert "calculator" in result["error"]


@pytest.mark.asyncio
async def test_run_tool_calculator_success():
    result = await run_tool("calculator", '{"expression": "2*(3+4)"}')
    assert result["ok"] is True
    assert result["result"] == 14


@pytest.mark.asyncio
async def test_run_tool_calculator_invalid_expression():
    result = await run_tool("calculator", '{"expression": "__import__(\\"os\\")"}')
    assert result["ok"] is False


@pytest.mark.asyncio
async def test_run_tool_db_query_write_rejected():
    result = await run_tool("db_query", '{"sql": "DELETE FROM documents"}')
    assert result["ok"] is False
    assert "read-only" in result["error"] or "not allowed" in result["error"]


# ---------------------------------------------------------------------------
# Calculator safe_eval
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("expr,expected", [
    ("1+2", 3),
    ("(1+2)*3.5", 10.5),
    ("2**10", 1024),
    ("7//2", 3),
    ("7%3", 1),
    ("-5 + 3", -2),
    ("sqrt(144)", 12.0),
    ("max(1, 9, 3)", 9),
    ("round(3.14159, 2)", 3.14),
    ("pi > 3", None),  # comparison not allowed → error path tested below
])
def test_safe_eval_basics(expr, expected):
    if expected is None:
        with pytest.raises(ValueError):
            safe_eval(expr)
    else:
        assert safe_eval(expr) == expected


@pytest.mark.parametrize("evil", [
    "__import__('os').system('dir')",
    "open('/etc/passwd')",
    "exec('1+1')",
    "lambda: 1",
    "[1,2,3]",
    "'abc' + 'def'",
    "1 if True else 2",
    "f'{1+1}'",
])
def test_safe_eval_rejects_dangerous_syntax(evil):
    with pytest.raises(ValueError):
        safe_eval(evil)


def test_safe_eval_rejects_too_long():
    with pytest.raises(ValueError):
        safe_eval("1+" * 150 + "1")


# ---------------------------------------------------------------------------
# db_query SQL validation
# ---------------------------------------------------------------------------

def test_validate_sql_allows_select():
    sql = _validate_sql("SELECT count(*) FROM documents")
    assert sql.startswith("SELECT")


def test_validate_sql_rejects_non_select():
    for bad in ["UPDATE documents SET content='x'", "DROP TABLE documents", "", ";x--"]:
        with pytest.raises(ToolError):
            _validate_sql(bad)


def test_validate_sql_rejects_multiple_statements():
    with pytest.raises(ToolError):
        _validate_sql("SELECT 1 FROM documents; SELECT 2 FROM documents")


def test_validate_sql_rejects_unknown_table():
    with pytest.raises(ToolError):
        _validate_sql("SELECT * FROM pg_user")


def test_validate_sql_blocks_cte_write():
    with pytest.raises(ToolError):
        _validate_sql("WITH t AS (SELECT 1) DELETE FROM documents")


def test_force_limit_appends_and_clamps():
    assert _force_limit("SELECT * FROM documents").endswith("LIMIT 50")
    assert _force_limit("SELECT * FROM documents LIMIT 10") == "SELECT * FROM documents LIMIT 10"
    clamped = _force_limit("SELECT * FROM documents LIMIT 9999")
    assert clamped.endswith("LIMIT 50")

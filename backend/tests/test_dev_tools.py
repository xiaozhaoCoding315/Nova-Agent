"""Unit tests for the developer tools: error_diagnosis + json_tool."""
import pytest

from app.core.tools import registry, run_tool


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_all_six_tools_registered():
    names = registry.names()
    for expected in ["calculator", "code_executor", "db_query",
                     "doc_parser", "error_diagnosis", "json_tool"]:
        assert expected in names


# ---------------------------------------------------------------------------
# error_diagnosis
# ---------------------------------------------------------------------------

PY_TRACEBACK = (
    "Traceback (most recent call last):\n"
    '  File "app/main.py", line 42, in handler\n'
    "    result = service.call()\n"
    '  File "app/service.py", line 88, in call\n'
    "    conn = psycopg.connect(dsn)\n"
    "psycopg.errors.OperationalError: connection refused"
)

JVM_TRACEBACK = (
    "java.lang.NullPointerException: Cannot invoke \"String.length()\"\n"
    "\tat com.nova.Agent.run(Agent.java:120)\n"
    "\tat com.nova.Main.main(Main.java:30)\n"
)


@pytest.mark.asyncio
async def test_error_diagnosis_python_traceback():
    result = await run_tool("error_diagnosis", {"error_text": PY_TRACEBACK})
    assert result["ok"] is True
    assert result["error_type"] == "psycopg.errors.OperationalError"
    assert "connection refused" in result["message"]
    assert {"file": "app/service.py", "line": 88} in result["locations"]
    assert len(result["locations"]) == 2


@pytest.mark.asyncio
async def test_error_diagnosis_jvm_traceback():
    result = await run_tool("error_diagnosis", {"error_text": JVM_TRACEBACK})
    assert result["ok"] is True
    assert result["error_type"] == "java.lang.NullPointerException"
    assert any("Agent.java" in loc["file"] for loc in result["locations"])


@pytest.mark.asyncio
async def test_error_diagnosis_rejects_empty():
    result = await run_tool("error_diagnosis", {"error_text": "   "})
    assert result["ok"] is False


@pytest.mark.asyncio
async def test_error_diagnosis_unknown_pattern_still_returns():
    result = await run_tool("error_diagnosis", {"error_text": "segfault at 0x00"})
    assert result["ok"] is True
    assert result["error_type"] is None
    assert result["line_count"] == 1


# ---------------------------------------------------------------------------
# json_tool
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_json_validate_ok():
    result = await run_tool("json_tool", {"data": '{"a": 1, "b": [1, 2]}'})
    assert result["ok"] is True
    assert result["valid"] is True
    assert result["top_type"] == "dict"
    assert result["top_keys"] == ["a", "b"]


@pytest.mark.asyncio
async def test_json_validate_bad_reports_position():
    result = await run_tool("json_tool", {"data": '{"a": 1,,}'})
    assert result["valid"] is False
    assert "第" in result["error"]


@pytest.mark.asyncio
async def test_json_format():
    result = await run_tool(
        "json_tool", {"data": '{"name":"nova"}', "operation": "format"}
    )
    assert result["valid"] is True
    assert '"name": "nova"' in result["formatted"]


@pytest.mark.asyncio
async def test_json_extract_nested():
    payload = '{"data": {"items": [{"id": 7, "tag": "x"}]}}'
    result = await run_tool(
        "json_tool",
        {"data": payload, "operation": "extract", "query": "data.items[0].id"},
    )
    assert result["found"] is True
    assert result["value"] == 7


@pytest.mark.asyncio
async def test_json_extract_missing_path():
    result = await run_tool(
        "json_tool",
        {"data": '{"a": 1}', "operation": "extract", "query": "a.b.c"},
    )
    assert result["found"] is False


@pytest.mark.asyncio
async def test_json_extract_requires_query():
    result = await run_tool(
        "json_tool", {"data": '{"a": 1}', "operation": "extract"}
    )
    assert result["ok"] is False  # ToolError → structured rejection

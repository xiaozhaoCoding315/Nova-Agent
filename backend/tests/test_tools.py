"""Tool system tests: registry contract + each built-in tool."""
import json
from unittest.mock import AsyncMock, patch

import pytest

from app.core.tools import build_registry, get_registry
from app.core.tools.base import ToolContext, ToolDefinition, ToolRegistry, validate_args
from app.core.tools.diagnose import parse_trace

USER = {"id": 1, "username": "admin", "role": "admin"}
CTX = ToolContext(user=USER, repo_ids=[])


# ---------- registry core ----------

def test_registry_has_all_tools_with_openai_specs():
    specs = get_registry().specs()
    names = {s["function"]["name"] for s in specs}
    assert names == {
        "run_code", "read_file", "list_files", "search_code", "impact_analysis",
        "diagnose_error", "write_files", "install_deps", "json_tool", "sql_tool", "fetch_url",
    }
    for spec in specs:
        assert spec["type"] == "function"
        assert spec["function"]["description"]
        assert spec["function"]["parameters"]["type"] == "object"


def test_registry_rejects_duplicate_registration():
    registry = ToolRegistry()
    tool = ToolDefinition(name="x", description="d", parameters={}, func=AsyncMock())
    registry.register(tool)
    with pytest.raises(ValueError):
        registry.register(tool)


def test_validate_args_type_and_required():
    schema = {
        "type": "object",
        "properties": {"a": {"type": "string"}, "n": {"type": "integer"}},
        "required": ["a"],
    }
    assert validate_args(schema, {"a": "x", "n": 1}) is None
    assert "missing required" in validate_args(schema, {"n": 1})
    assert "must be of type" in validate_args(schema, {"a": 5})


@pytest.mark.asyncio
async def test_unknown_tool_returns_error_not_raise():
    result = await get_registry().execute("nope", {}, CTX)
    assert result["ok"] is False and "unknown tool" in result["error"]


@pytest.mark.asyncio
async def test_invalid_args_are_business_errors():
    result = await get_registry().execute("sql_tool", {"sql": 123}, CTX)
    assert result["ok"] is False and result["business"] is True


# ---------- json_tool ----------

@pytest.mark.asyncio
async def test_json_tool_validate_format_extract_convert():
    registry = build_registry()

    r = await registry.execute("json_tool", {"input": '{"a": [1, 2], "b": {"c": 3}}'}, CTX)
    assert r["ok"] and r["output"]["valid"] and r["output"]["root_type"] == "dict"

    r = await registry.execute("json_tool", {"input": '{"a":1}', "mode": "extract", "path": "a"}, CTX)
    assert r["ok"] and r["output"]["value"] == 1

    r = await registry.execute("json_tool", {"input": "a: 1\nb:\n  - x", "mode": "convert", "to": "json"}, CTX)
    assert r["ok"] and json.loads(r["output"]["converted"])["a"] == 1

    r = await registry.execute("json_tool", {"input": "{bad json", "mode": "validate", "format": "json"}, CTX)
    assert r["ok"] is False and r["business"] is True


@pytest.mark.asyncio
async def test_json_tool_extract_missing_path_is_business_error():
    r = await build_registry().execute(
        "json_tool", {"input": '{"a":1}', "mode": "extract", "path": "a.b"}, CTX
    )
    assert r["ok"] is False and r["business"] is True and "路径不存在" in r["error"]


# ---------- sql_tool ----------

@pytest.mark.asyncio
async def test_sql_tool_review_findings():
    r = await build_registry().execute(
        "sql_tool", {"sql": "select * from users where id = 1 or 1=1"}, CTX
    )
    rules = {f["rule"] for f in r["output"]["findings"]}
    assert "select_star" in rules and "always_true" in rules


@pytest.mark.asyncio
async def test_sql_tool_format_uppercases_keywords_outside_strings():
    r = await build_registry().execute(
        "sql_tool", {"sql": "select name from t where note = 'from select'", "mode": "format"}, CTX
    )
    formatted = r["output"]["formatted"]
    assert "SELECT" in formatted and "FROM" in formatted
    assert "'from select'" in formatted  # string literal untouched


@pytest.mark.asyncio
async def test_sql_tool_flags_delete_without_where():
    r = await build_registry().execute("sql_tool", {"sql": "delete from users"}, CTX)
    sevs = {f["rule"]: f["severity"] for f in r["output"]["findings"]}
    assert sevs.get("no_where") == "critical"


# ---------- diagnose_error ----------

def test_parse_python_traceback():
    tb = '''Traceback (most recent call last):
  File "/app/main.py", line 10, in <module>
    run()
  File "/app/service.py", line 42, in run
    raise ValueError("boom")
ValueError: boom'''
    parsed = parse_trace(tb)
    assert parsed["language"] == "python"
    assert parsed["error_type"] == "ValueError"
    assert parsed["message"] == "boom"
    assert {"file": "/app/service.py", "line": 42, "func": "run"} in parsed["frames"]


def test_parse_jvm_stack():
    tb = """Exception in thread "main" java.lang.NullPointerException: Cannot invoke
\tat com.demo.UserService.find(UserService.java:88)
\tat com.demo.Main.main(Main.java:12)"""
    parsed = parse_trace(tb)
    assert parsed["language"] == "java"
    assert parsed["error_type"] == "java.lang.NullPointerException"
    assert parsed["frames"][0] == {"file": "UserService.java", "line": 88, "func": "com.demo.UserService.find"}


def test_parse_node_stack():
    tb = """TypeError: x is not a function
    at handler (/app/routes/index.js:23:9)
    at process (/app/server.js:10:5)"""
    parsed = parse_trace(tb)
    assert parsed["language"] == "javascript"
    assert parsed["error_type"] == "TypeError"
    assert parsed["frames"][0]["file"] == "/app/routes/index.js"


def test_parse_go_panic():
    tb = """panic: runtime error: index out of range [5] with length 3
goroutine 1 [running]:
main.process()
\t/app/main.go:17 +0x1a"""
    parsed = parse_trace(tb)
    assert parsed["language"] == "go"
    assert "index out of range" in parsed["message"]
    assert parsed["frames"][0] == {"file": "/app/main.go", "line": 17, "func": ""}


@pytest.mark.asyncio
async def test_diagnose_requires_stack():
    r = await build_registry().execute("diagnose_error", {"stack": "  "}, CTX)
    assert r["ok"] is False and r["business"] is True


# ---------- search_code ----------

@pytest.mark.asyncio
async def test_search_code_merges_symbols_and_snippets(monkeypatch):
    from app.models.domain import RetrievedChunk

    async def fake_symbols(query, repo_ids=None, limit=8):
        return [{"name": "login", "kind": "function", "path": "auth.py",
                 "line_start": 10, "line_end": 20, "signature": "def login(...)"}]

    async def fake_retrieve(query, top_k=8, repo_ids=None):
        return [RetrievedChunk(id="1", content="def login()", path="auth.py",
                               line_start=10, line_end=20, score_type="dense")]

    monkeypatch.setattr("app.core.tools.search_code.search_symbols", fake_symbols)
    monkeypatch.setattr("app.core.tools.search_code.retrieve", fake_retrieve)

    r = await build_registry().execute("search_code", {"query": "login"}, CTX)
    assert r["ok"]
    assert r["output"]["symbols"][0]["path"] == "auth.py"
    assert r["output"]["snippets"][0]["line_start"] == 10


# ---------- run_code ----------

@pytest.mark.asyncio
async def test_run_code_requires_some_files():
    r = await build_registry().execute("run_code", {}, CTX)
    assert r["ok"] is False and r["business"] is True


@pytest.mark.asyncio
async def test_run_code_blocks_risky_code():
    r = await build_registry().execute(
        "run_code", {"files": {"main.py": "import os; os.system('rm -rf /')"}}, CTX
    )
    assert r["ok"] is False and "安全规则" in r["error"]


@pytest.mark.asyncio
async def test_run_code_reports_unavailable_sandbox(monkeypatch):
    async def unavailable():
        return {"available": False, "reason": "docker down (test)"}

    monkeypatch.setattr("app.core.tools.run_code.sandbox_status", unavailable)
    r = await build_registry().execute("run_code", {"files": {"main.py": "print(1)"}}, CTX)
    assert r["ok"] is False and "沙箱不可用" in r["error"]


@pytest.mark.asyncio
async def test_run_code_executes_when_sandbox_available(monkeypatch):
    async def available():
        return {"available": True, "image": "nova-sandbox:latest",
                "builder_available": True, "builder_image": "nova-builder:latest"}

    async def fake_execute(files, command=None, stdin="", timeout=None, **kwargs):
        assert kwargs.get("image") == "nova-builder:latest"
        return {"stdout": "1\n", "stderr": "", "exit_code": 0, "timed_out": False,
                "sandboxed": True, "command": command or "python main.py"}

    monkeypatch.setattr("app.core.tools.run_code.sandbox_status", available)
    monkeypatch.setattr("app.core.tools.run_code.sandbox_execute", fake_execute)
    monkeypatch.setattr("app.core.tools.run_code.check_sandbox_quota", AsyncMock())
    monkeypatch.setattr("app.core.tools.run_code.log_audit", AsyncMock())

    r = await build_registry().execute(
        "run_code", {"files": {"main.py": "print(1)"}, "env": "builder"}, CTX
    )
    assert r["ok"] and r["output"]["exit_code"] == 0 and r["output"]["stdout"] == "1\n"


@pytest.mark.asyncio
async def test_install_deps_admin_only():
    ctx = ToolContext(user={"id": 2, "role": "demo"}, permission_mode="auto")
    r = await build_registry().execute("install_deps", {}, ctx)
    assert r["ok"] is False and r["business"] is True
    assert "管理员" in r["error"]


@pytest.mark.asyncio
async def test_install_deps_requires_network_switch(monkeypatch):
    from app.config import settings as app_settings
    monkeypatch.setattr(app_settings, "sandbox_allow_network", False)
    ctx = ToolContext(user={"id": 1, "role": "admin"}, permission_mode="auto")
    r = await build_registry().execute("install_deps", {}, ctx)
    assert r["ok"] is False and r["business"] is True
    assert "SANDBOX_ALLOW_NETWORK" in r["error"]


# ---------- fetch_url ----------

@pytest.mark.asyncio
async def test_fetch_url_rejects_bad_scheme():
    from app.core.tools.fetch_url import _resolves_to_public
    r = await build_registry().execute("fetch_url", {"url": "file:///etc/passwd"}, CTX)
    assert r["ok"] is False and "http" in r["error"]

    assert _resolves_to_public("localhost") is False
    assert _resolves_to_public("127.0.0.1") is False
    assert _resolves_to_public("192.168.1.10") is False


@pytest.mark.asyncio
async def test_fetch_url_blocks_private_host():
    r = await build_registry().execute("fetch_url", {"url": "http://192.168.150.128:8000/"}, CTX)
    assert r["ok"] is False and "内网" in r["error"]
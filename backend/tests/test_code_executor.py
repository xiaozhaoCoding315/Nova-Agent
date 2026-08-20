"""Unit tests for the code_executor skill (sandbox in the agent loop)."""
import pytest

from app.core.tools import registry, run_tool
from app.core.tools.code_executor import execute_code, code_executor_tool


def test_code_executor_registered():
    assert "code_executor" in registry.names()


@pytest.mark.asyncio
async def test_run_tool_code_executor_local_run():
    """Real execution path (docker if available, direct otherwise)."""
    code = "print(sum(range(1, 101)))"
    result = await run_tool("code_executor", {"code": code})
    assert result["tool"] == "code_executor"
    assert result["ok"] is True
    assert "5050" in result["stdout"]


@pytest.mark.asyncio
async def test_code_executor_runtime_error_is_reported_not_raised():
    result = await run_tool(
        "code_executor", {"code": "raise ValueError('boom')"}
    )
    assert result["ok"] is False
    assert result["exit_code"] != 0
    assert "boom" in (result["stderr"] or "")


@pytest.mark.asyncio
async def test_code_executor_rejects_dangerous_code():
    for evil in [
        "import os" + chr(10) + "os.system('rm -rf /')",
        "__import__('os').getcwd()",
        "eval('1+1')",
    ]:
        result = await run_tool("code_executor", {"code": evil})
        assert result["ok"] is False
        assert "risk check" in result["error"]


@pytest.mark.asyncio
async def test_code_executor_rejects_empty_and_oversize():
    assert (await run_tool("code_executor", {"code": "   "}))["ok"] is False
    assert (await run_tool("code_executor", {"code": "x" * 9000}))["ok"] is False


@pytest.mark.asyncio
async def test_code_executor_warn_level_still_runs():
    """WARN patterns (sudo/pip install) pass the check and execute."""
    result = await run_tool(
        "code_executor",
        {"code": "print('pip install is mentioned here')"},
    )
    assert result["ok"] is True
    assert "pip install" in result["stdout"]


def test_tool_spec_mentions_sandbox():
    assert "sandbox" in code_executor_tool.description.lower() or "沙箱" in code_executor_tool.description

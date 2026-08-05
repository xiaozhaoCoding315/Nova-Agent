import pytest
from app.core.sandbox.runtime import execute_in_sandbox

@pytest.mark.asyncio
@pytest.mark.integration
async def test_sandbox_executes_code():
    result = await execute_in_sandbox('print("integration test")', language="python", timeout=5)
    assert result["exit_code"] == 0
    assert "integration test" in result["stdout"]

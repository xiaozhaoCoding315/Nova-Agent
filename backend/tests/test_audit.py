import pytest
from app.core.security.audit import log_audit, get_audit_log, get_audit_stats

@pytest.mark.asyncio
async def test_log_and_retrieve_audit():
    await log_audit("code_execution", user_id="test-user", details={"code": "print(1)"}, risk_level="safe")
    logs = get_audit_log(action="code_execution")
    assert len(logs) >= 1
    assert logs[-1]["action"] == "code_execution"
    assert logs[-1]["user_id"] == "test-user"

@pytest.mark.asyncio
async def test_audit_stats():
    await log_audit("risk_blocked", details={"reason": "rm -rf"})
    stats = get_audit_stats()
    assert stats["total_entries"] >= 1

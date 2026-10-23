"""Static contract tests for endpoint helpers.

The P0 quota rollout accidentally awaited sync helpers, which only failed at
request time. This test catches that class of mistake before deployment.
"""
import ast
import inspect
from pathlib import Path

from app.core.security import limits

FORBIDDEN_AWAIT = {"check_job_quota", "check_search_quota"}


def test_quota_helpers_stay_synchronous():
    assert not inspect.iscoroutinefunction(limits.check_job_quota)
    assert not inspect.iscoroutinefunction(limits.check_search_quota)


def test_api_never_awaits_sync_quota_helpers():
    offenders: list[str] = []
    for path in Path("app/api/v1").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Await):
                continue
            call = node.value
            if not isinstance(call, ast.Call):
                continue
            func = call.func
            name = getattr(func, "id", None) or getattr(func, "attr", None)
            if name in FORBIDDEN_AWAIT:
                offenders.append(f"{path.name}:{node.lineno}: await {name}()")
    assert not offenders, "\n".join(offenders)

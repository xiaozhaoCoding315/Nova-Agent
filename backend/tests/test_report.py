"""Delivery report is deterministic and reflects real evidence."""
from app.core.agent.report import build_turn_report

EVIDENCE = {"verified": 2, "missing": 0, "out_of_range": 0, "skipped": 0, "executed": True}
USAGE = {"prompt_tokens": 10, "completion_tokens": 5}


def _report(**overrides):
    base = dict(
        user_message="给这个函数写测试并跑通",
        repos=[{"id": "r1", "name": "demo"}],
        permission_mode="ask",
        tools=[],
        edits=[],
        evidence=EVIDENCE,
        usage=USAGE,
        rounds=1,
        elapsed_ms=1200,
        final_text="已完成",
        errors=[],
    )
    base.update(overrides)
    return build_turn_report(**base)


def test_successful_test_command_is_verified():
    report = _report(tools=[{
        "name": "run_code", "ok": True, "ms": 100,
        "command": "python -m pytest -q", "exit_code": 0, "timed_out": False,
    }])
    assert report["status"] == "verified"
    assert report["commands"][0]["exit_code"] == 0
    assert report["checks"][1]["status"] == "passed"
    assert report["unverified"] == []


def test_pending_edit_makes_report_partial():
    report = _report(
        tools=[{
            "name": "run_code", "ok": True, "ms": 100,
            "command": "python -m pytest -q", "exit_code": 0, "timed_out": False,
        }],
        edits=[{"files": ["app/main.py"], "staged": True, "status": "pending"}],
    )
    assert report["status"] == "partial"
    assert report["files_changed"] == [{"path": "app/main.py", "status": "pending"}]
    assert any("尚未批准" in item for item in report["unverified"])


def test_no_execution_is_unverified():
    report = _report(final_text="我读了一下代码")
    assert report["status"] == "partial"  # citations were verified, but nothing ran
    assert any("没有在沙箱中执行" in item for item in report["unverified"])


def test_errors_mark_report_failed():
    report = _report(errors=["模型调用失败：timeout"])
    assert report["status"] == "failed"
    assert report["errors"]

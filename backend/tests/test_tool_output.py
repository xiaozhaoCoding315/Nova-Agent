"""Tool result serialization: valid JSON, head/tail truncation, previews."""
import json

from app.core.agent.tool_output import build_preview, serialize_tool_result


def test_short_result_is_untouched():
    result = {"ok": True, "output": {"a": 1}, "ms": 3}
    parsed = json.loads(serialize_tool_result("json_tool", result))
    assert parsed["output"] == {"a": 1}
    assert parsed["ms"] == 3
    assert "_truncated" not in parsed


def test_long_stdout_keeps_head_tail_and_end_marker():
    long_text = "A" * 30_000 + "FAILED"
    result = {
        "ok": True,
        "output": {"stdout": long_text, "stderr": "", "exit_code": 1, "command": "pytest"},
        "ms": 5,
    }
    parsed = json.loads(serialize_tool_result("run_command", result))
    stdout = parsed["output"]["stdout"]
    assert parsed["_truncated"] is True
    assert parsed["_truncated_chars"] > 0
    assert stdout.startswith("A")
    assert stdout.endswith("FAILED")
    assert "truncated" in stdout


def test_error_result_is_preserved():
    parsed = json.loads(
        serialize_tool_result("grep", {"ok": False, "error": "bad regex", "ms": 0})
    )
    assert parsed["ok"] is False
    assert parsed["error"] == "bad regex"


def test_large_list_is_capped_with_count():
    result = {
        "ok": True,
        "output": {"files": [{"path": f"f{i}.py"} for i in range(200)]},
        "ms": 1,
    }
    parsed = json.loads(serialize_tool_result("list_files", result))
    assert len(parsed["output"]["files"]) == 50
    assert parsed["output"]["files_truncated"] == 150
    assert parsed["_truncated"] is True


def test_preview_prefers_stderr_tail_for_exec_tools():
    result = {
        "ok": True,
        "output": {
            "stdout": "x" * 1000,
            "stderr": "Traceback: boom",
            "exit_code": 1,
            "command": "pytest -q",
        },
        "ms": 5,
    }
    preview = build_preview("run_command", result)
    assert "pytest -q" in preview
    assert "exit_code=1" in preview
    assert "boom" in preview


def test_preview_for_error_result():
    preview = build_preview("grep", {"ok": False, "error": "bad regex", "ms": 0})
    assert preview == "错误：bad regex"

"""Fixed-runner diagnostics: parsing, argv construction, execution and policy."""
import json

import pytest

from app.core.tools import diagnostics_parse as dp


def test_normalize_path_accepts_relative_absolute_and_sandbox_paths(tmp_path):
    assert dp.normalize_path("backend/app.py", tmp_path) == "backend/app.py"
    assert dp.normalize_path(str(tmp_path / "backend" / "app.py"), tmp_path) == (
        "backend/app.py"
    )
    assert dp.normalize_path("/workspace/backend/app.py", tmp_path) == (
        "backend/app.py"
    )
    assert dp.normalize_path("backend\\app.py", tmp_path) == "backend/app.py"


def test_normalize_path_rejects_escapes(tmp_path):
    assert dp.normalize_path("../outside.py", tmp_path) is None
    assert dp.normalize_path(str(tmp_path.parent / "outside.py"), tmp_path) is None
    assert dp.normalize_path("", tmp_path) is None


def test_parse_ruff_json_normalizes_and_sorts(tmp_path):
    payload = [
        {
            "code": "F401",
            "message": "`os` imported but unused",
            "filename": str(tmp_path / "backend" / "app.py"),
            "location": {"row": 12, "column": 5},
        },
        {
            "code": "E501",
            "message": "line too long",
            "filename": "a.py",
            "location": {"row": 3, "column": 88},
        },
    ]
    diagnostics, errors = dp.parse_ruff_json(json.dumps(payload), tmp_path)

    assert errors == 0
    assert diagnostics[0] == {
        "path": "backend/app.py",
        "line": 12,
        "column": 5,
        "severity": "error",
        "code": "F401",
        "message": "`os` imported but unused",
        "source": "ruff",
    }
    assert [item["path"] for item in dp.sort_diagnostics(diagnostics)] == [
        "a.py", "backend/app.py",
    ]


def test_parse_ruff_json_handles_empty_and_broken_output(tmp_path):
    assert dp.parse_ruff_json("", tmp_path) == ([], 0)
    assert dp.parse_ruff_json("not json", tmp_path) == ([], 1)
    assert dp.parse_ruff_json("{}", tmp_path) == ([], 1)


def test_parse_mypy_text_handles_columns_notes_and_continuations(tmp_path):
    text = (
        "backend/app/x.py:12:5: error: Incompatible types  [assignment]\n"
        "    value = \"x\"\n"
        "backend/app/y.py:7: note: See https://example.test  [misc]\n"
        "../outside.py:1:1: error: nope  [misc]\n"
        "Success: no issues found in 2 source files\n"
    )
    diagnostics, errors = dp.parse_mypy_text(text, tmp_path)

    assert errors == 1
    assert [item["path"] for item in diagnostics] == [
        "backend/app/x.py", "backend/app/y.py",
    ]
    assert diagnostics[0]["line"] == 12 and diagnostics[0]["column"] == 5
    assert diagnostics[0]["code"] == "assignment"
    assert diagnostics[0]["message"].endswith('value = "x"')
    assert diagnostics[1]["severity"] == "info"
    assert diagnostics[1]["column"] == 0


def test_parse_tsc_text_maps_message_and_continuations(tmp_path):
    text = (
        "src/a.ts(3,7): error TS2322: Type 'string' is not assignable.\n"
        "  Type 'string' is not assignable to type 'number'.\n"
        "src/b.ts(1,1): message TS9999: hello\n"
        "Found 1 error.\n"
    )
    diagnostics, errors = dp.parse_tsc_text(text, tmp_path)

    assert errors == 0
    assert [item["code"] for item in diagnostics] == ["TS2322", "TS9999"]
    assert diagnostics[0]["severity"] == "error"
    assert "not assignable to type 'number'" in diagnostics[0]["message"]
    assert diagnostics[1]["severity"] == "info"


def test_summarize_counts_files_errors_warnings(tmp_path):
    payload = [
        {"code": "F401", "message": "a", "filename": "a.py",
         "location": {"row": 1, "column": 1}},
        {"code": "E501", "message": "b", "filename": "a.py",
         "location": {"row": 2, "column": 1}},
        {"code": "F841", "message": "c", "filename": "b.py",
         "location": {"row": 1, "column": 1}},
    ]
    diagnostics, _ = dp.parse_ruff_json(json.dumps(payload), tmp_path)
    assert dp.summarize(diagnostics) == {
        "files": 2, "errors": 3, "warnings": 0, "total": 3,
    }


def test_tail_text_redacts_secrets():
    text = "x" * 10 + " token sk-" + "a" * 24
    cleaned = dp.tail_text(text, limit=4000)
    assert "sk-" + "a" * 24 not in cleaned
    assert "[REDACTED]" in cleaned

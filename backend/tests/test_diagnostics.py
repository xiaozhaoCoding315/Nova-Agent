"""Fixed-runner diagnostics: parsing, argv construction, execution and policy."""
import json
from pathlib import Path

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


def test_normalize_path_keeps_host_root_under_workspace():
    # A host root that itself lives under /workspace must not lose its
    # basename when the absolute runner path is mapped back.
    root = Path("/workspace/repo")
    assert dp.normalize_path("/workspace/repo/backend/app.py", root) == (
        "backend/app.py"
    )


def test_parse_tsc_continuation_is_redacted(tmp_path):
    secret = "sk-" + "b" * 24
    text = (
        "src/a.ts(3,7): error TS2322: Type 'string' is not assignable.\n"
        f"  Type '\"{secret}\"' is not assignable to type 'number'.\n"
    )
    diagnostics, errors = dp.parse_tsc_text(text, tmp_path)

    assert errors == 0
    assert len(diagnostics) == 1
    message = diagnostics[0]["message"]
    assert "[REDACTED]" in message
    assert secret not in message
    assert "is not assignable to type 'number'" in message


def test_parse_tsc_skips_count_summary(tmp_path):
    text = (
        "src/a.ts(3,7): error TS2322: Type 'string' is not assignable.\n"
        "src/b.ts(10,1): error TS2345: Argument of type 'string' is not "
        "assignable to parameter of type 'number'.\n"
        "Found 2 errors in 2 files.\n"
    )
    diagnostics, errors = dp.parse_tsc_text(text, tmp_path)

    assert errors == 0
    assert [(item["path"], item["line"], item["message"])
            for item in diagnostics] == [
        ("src/a.ts", 3, "Type 'string' is not assignable."),
        (
            "src/b.ts",
            10,
            "Argument of type 'string' is not assignable to parameter of "
            "type 'number'.",
        ),
    ]


def test_parse_tsc_skips_same_file_summary(tmp_path):
    text = (
        "src/a.ts(3,7): error TS2322: Type 'string' is not assignable.\n"
        "src/a.ts(9,2): error TS2345: Argument of type 'string' is not "
        "assignable to parameter of type 'number'.\n"
        "Found 2 errors in the same file, starting at: src/a.ts:3\n"
    )
    diagnostics, errors = dp.parse_tsc_text(text, tmp_path)

    assert errors == 0
    assert [item["message"] for item in diagnostics] == [
        "Type 'string' is not assignable.",
        "Argument of type 'string' is not assignable to parameter of type "
        "'number'.",
    ]


def test_parse_tsc_skips_errors_files_table(tmp_path):
    text = (
        "src/a.ts(3,7): error TS2322: Type 'string' is not assignable.\n"
        "src/b.ts(10,1): error TS2345: Argument of type 'string' is not "
        "assignable to parameter of type 'number'.\n"
        "Errors  Files\n"
        "     1  src/a.ts:3\n"
        "     2  src/b.ts:10\n"
    )
    diagnostics, errors = dp.parse_tsc_text(text, tmp_path)

    assert errors == 0
    assert [item["message"] for item in diagnostics] == [
        "Type 'string' is not assignable.",
        "Argument of type 'string' is not assignable to parameter of type "
        "'number'.",
    ]


def test_continuation_after_rejected_line_is_not_attached(tmp_path):
    mypy_text = (
        "backend/app/x.py:1:1: error: first  [misc]\n"
        "../outside.py:2:2: error: escaped  [misc]\n"
        "    stray continuation\n"
    )
    diagnostics, errors = dp.parse_mypy_text(mypy_text, tmp_path)

    assert errors == 2
    assert len(diagnostics) == 1
    assert diagnostics[0]["message"] == "first"

    tsc_text = (
        "src/a.ts(1,1): error TS2322: first\n"
        "../outside.ts(2,2): error TS2322: escaped\n"
        "  stray continuation\n"
    )
    diagnostics, errors = dp.parse_tsc_text(tsc_text, tmp_path)

    assert errors == 2
    assert len(diagnostics) == 1
    assert diagnostics[0]["message"] == "first"

    assert dp.parse_mypy_text("    orphan continuation\n", tmp_path) == ([], 1)
    assert dp.parse_tsc_text("    orphan continuation\n", tmp_path) == ([], 1)


def test_tail_text_redacts_before_truncating():
    secret = "sk-" + "c" * 24
    text = "x" * 10 + " token " + secret
    cleaned = dp.tail_text(text, limit=15)

    assert len(cleaned) == 15
    assert cleaned.endswith("[REDACTED]")
    assert secret not in cleaned
    assert dp.tail_text(text, limit=0) == ""
    assert dp.tail_text(text, limit=-1) == ""


from unittest.mock import AsyncMock

from app.config import settings
from app.core.security.policy import decide_tool
from app.core.tools import build_registry
from app.core.tools import diagnostics as diag
from app.core.tools.base import ToolBusinessError, ToolContext

USER = {"id": 7, "username": "u", "role": "demo"}


def _ctx(mode="auto", repo_ids=("r-1",)):
    return ToolContext(user=USER, repo_ids=list(repo_ids), permission_mode=mode)


def test_build_argv_uses_fixed_flags(tmp_path):
    assert diag.build_argv("ruff", ["backend"], "", "/tmp/c") == [
        "ruff", "check", "--output-format", "json", "--no-cache", "--quiet",
        "backend",
    ]
    assert diag.build_argv("mypy", [], "", "/tmp/c") == [
        "mypy", "--no-incremental", "--no-error-summary",
        "--show-column-numbers", "--show-error-codes", "--no-color-output",
        "--cache-dir", "/tmp/c", ".",
    ]
    assert diag.build_argv("tsc", ["ignored"], "tsconfig.json", "/tmp/c") == [
        "tsc", "--noEmit", "--incremental", "false", "--pretty", "false",
        "-p", "tsconfig.json",
    ]


@pytest.mark.asyncio
async def test_run_diagnostics_rejects_bad_tool_and_paths(monkeypatch):
    monkeypatch.setattr(settings, "nova_mode", "server")
    with pytest.raises(ToolBusinessError, match="ruff"):
        await diag.run_diagnostics({"tool": "eslint"}, _ctx())

    monkeypatch.setattr(
        "app.core.indexing.pipeline.get_repo",
        AsyncMock(return_value={"root_path": str(_repo_root())}),
    )
    with pytest.raises(ToolBusinessError, match="相对路径"):
        await diag.run_diagnostics(
            {"tool": "ruff", "paths": ["/etc/passwd"]}, _ctx()
        )
    with pytest.raises(ToolBusinessError, match="越出仓库"):
        await diag.run_diagnostics(
            {"tool": "ruff", "paths": ["../outside"]}, _ctx()
        )
    with pytest.raises(ToolBusinessError, match="最多"):
        await diag.run_diagnostics(
            {"tool": "ruff", "paths": [f"p{i}.py" for i in range(21)]}, _ctx()
        )


def _repo_root() -> Path:
    base = Path(__file__).resolve().parents[2]
    return base


@pytest.mark.asyncio
async def test_run_diagnostics_sandbox_uses_sanitized_copy(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "nova_mode", "server")
    monkeypatch.setattr(
        "app.core.indexing.pipeline.get_repo",
        AsyncMock(return_value={"root_path": str(tmp_path)}),
    )
    monkeypatch.setattr(
        diag, "sandbox_status",
        AsyncMock(return_value={
            "available": True, "builder_available": True, "node_available": True,
        }),
    )
    monkeypatch.setattr(diag, "check_sandbox_quota", AsyncMock())
    execute = AsyncMock(return_value={
        "stdout": json.dumps([{
            "code": "F401", "message": "unused",
            "filename": "backend/app.py",
            "location": {"row": 2, "column": 1},
        }]),
        "stderr": "",
        "exit_code": 1,
        "timed_out": False,
        "duration_ms": 42,
    })
    monkeypatch.setattr(diag, "sandbox_execute", execute)

    output = await diag.run_diagnostics({"tool": "ruff"}, _ctx())

    kwargs = execute.await_args.kwargs
    assert kwargs["workspace_dir"] == str(tmp_path)
    assert kwargs["sanitized_workspace"] is True
    assert kwargs["include_git"] is False
    assert kwargs["image"] == settings.sandbox_builder_image
    assert output["ok"] is True and output["exit_code"] == 1
    assert output["runner"] == {
        "name": "ruff", "version": "0.8.6", "executor": "sandbox",
    }
    assert output["summary"] == {
        "files": 1, "errors": 1, "warnings": 0, "total": 1,
    }
    assert output["diagnostics"][0]["path"] == "backend/app.py"


@pytest.mark.asyncio
async def test_run_diagnostics_tsc_uses_node_image_and_deps(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "nova_mode", "server")
    (tmp_path / "tsconfig.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        "app.core.indexing.pipeline.get_repo",
        AsyncMock(return_value={"root_path": str(tmp_path)}),
    )
    monkeypatch.setattr(
        diag, "sandbox_status",
        AsyncMock(return_value={
            "available": True, "builder_available": True, "node_available": True,
        }),
    )
    monkeypatch.setattr(diag, "check_sandbox_quota", AsyncMock())
    execute = AsyncMock(return_value={
        "stdout": "", "stderr": "", "exit_code": 0,
        "timed_out": False, "duration_ms": 10,
    })
    monkeypatch.setattr(diag, "sandbox_execute", execute)

    output = await diag.run_diagnostics({"tool": "tsc"}, _ctx())

    kwargs = execute.await_args.kwargs
    assert kwargs["image"] == settings.sandbox_node_image
    assert kwargs["deps_mount"] == "/workspace/node_modules"
    assert kwargs["deps_volume"].startswith("nova-node-deps-")
    assert output["summary"]["total"] == 0


@pytest.mark.asyncio
async def test_run_diagnostics_rejects_missing_tsconfig(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "nova_mode", "server")
    monkeypatch.setattr(
        "app.core.indexing.pipeline.get_repo",
        AsyncMock(return_value={"root_path": str(tmp_path)}),
    )
    with pytest.raises(ToolBusinessError, match="tsconfig"):
        await diag.run_diagnostics({"tool": "tsc"}, _ctx())


@pytest.mark.asyncio
async def test_run_diagnostics_reports_runner_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "nova_mode", "host")
    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(
        "app.core.indexing.pipeline.get_repo",
        AsyncMock(return_value={"root_path": str(tmp_path)}),
    )
    monkeypatch.setattr(
        diag, "resolve_host_argv", lambda tool, root, argv: ["ruff", *argv[1:]]
    )
    monkeypatch.setattr(diag, "_version_for", AsyncMock(return_value="ruff 0.17.3"))
    from app.core.exec import service as exec_service
    monkeypatch.setattr(
        exec_service, "run_argv_host",
        AsyncMock(return_value={
            "stdout": "", "stderr": "configuration error: no pyproject.toml",
            "exit_code": 2, "timed_out": False, "duration_ms": 5,
            "warning": exec_service.WARNING,
        }),
    )

    with pytest.raises(ToolBusinessError, match="无法运行 ruff"):
        await diag.run_diagnostics({"tool": "ruff"}, _ctx())


def test_diagnostics_policy_local_readonly_denies_and_ask_requires_approval(monkeypatch):
    monkeypatch.setattr(settings, "nova_mode", "local")
    tool = build_registry().get("diagnostics")
    assert tool is not None
    denied = decide_tool("diagnostics", tool.category, tool.capabilities, {"tool": "ruff"}, _ctx("readonly"))
    assert denied.allowed is False
    ask = decide_tool("diagnostics", tool.category, tool.capabilities, {"tool": "ruff"}, _ctx("ask"))
    assert ask.allowed is False and ask.requires_approval is True
    auto = decide_tool("diagnostics", tool.category, tool.capabilities, {"tool": "ruff"}, _ctx("auto"))
    assert auto.allowed is True


def test_diagnostics_hidden_in_local_readonly(monkeypatch):
    monkeypatch.setattr(settings, "nova_mode", "local")
    names = {
        spec["function"]["name"]
        for spec in build_registry().specs(permission_mode="readonly")
    }
    assert "diagnostics" not in names

    monkeypatch.setattr(settings, "nova_mode", "server")
    names = {
        spec["function"]["name"]
        for spec in build_registry().specs(permission_mode="readonly")
    }
    assert "diagnostics" in names

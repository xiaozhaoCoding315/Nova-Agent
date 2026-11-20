"""Thesis-mode boundary: tool policy, archive guards, templates and file guard."""
from __future__ import annotations

import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.security import policy
from app.core.thesis import service
from app.core.thesis.file_guard import ThesisFileGuard
from app.core.thesis.rules.builtin import get_template_strict
from app.core.tools import thesis as thesis_tools
from app.core.tools.base import ToolRegistry


def _ctx(**overrides) -> SimpleNamespace:
    base = {
        "permission_mode": "auto",
        "product_mode": "dev",
        "protected_roots": (),
        "repo_roots": {},
        "user": {"role": "admin"},
        "approval_granted": False,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_thesis_mode_requires_approval_for_sensitive_tools():
    decision = policy.decide_tool(
        "write_files", "write", None, {"path": "src/app.py"}, _ctx(product_mode="thesis"),
    )
    assert not decision.allowed
    assert decision.requires_approval


def test_thesis_mode_allows_read_only_tools_without_prompt():
    decision = policy.decide_tool(
        "read_file", "read", None, {"path": "src/app.py"}, _ctx(product_mode="thesis"),
    )
    assert decision.allowed


def test_approved_sensitive_call_is_allowed():
    decision = policy.decide_tool(
        "write_files", "write", None, {"path": "src/app.py"},
        _ctx(product_mode="thesis", approval_granted=True),
    )
    assert decision.allowed


def test_dev_mode_keeps_auto_semantics():
    decision = policy.decide_tool(
        "write_files", "write", None, {"path": "src/app.py"}, _ctx(),
    )
    assert decision.allowed


def test_protected_path_is_denied(tmp_path: Path):
    root = tmp_path / "thesis"
    root.mkdir()
    decision = policy.decide_tool(
        "write_files", "write", None, {"path": "thesis/thesis.docx"},
        _ctx(product_mode="thesis", protected_roots=(str(root),),
             repo_roots={"r": str(tmp_path)}, approval_granted=True),
    )
    assert not decision.allowed
    assert "论文原始文件受保护" in decision.reason


def test_protected_command_is_denied(tmp_path: Path):
    root = tmp_path / "thesis"
    root.mkdir()
    decision = policy.decide_tool(
        "run_command", "execute", None, {"command": f"cat {root}/thesis.docx"},
        _ctx(product_mode="thesis", protected_roots=(str(root),),
             approval_granted=True),
    )
    assert not decision.allowed
    assert "论文原始文件受保护" in decision.reason


def test_thesis_tools_are_hidden_from_dev_sessions():
    registry = ToolRegistry()
    for tool in thesis_tools.ALL:
        registry.register(tool)

    dev_names = {item["function"]["name"] for item in registry.specs(product_mode="dev")}
    thesis_names = {
        item["function"]["name"] for item in registry.specs(product_mode="thesis")
    }
    assert dev_names == set()
    assert thesis_names == {
        "thesis_outline", "thesis_read_section", "thesis_search_text",
        "thesis_issues", "thesis_reference_lookup",
    }


def test_strict_template_lookup_rejects_unknown_ids():
    with pytest.raises(ValueError, match="未知论文模板"):
        get_template_strict("no-such-template")
    assert get_template_strict(None)["id"]


def test_docx_archive_rejects_compression_bombs(tmp_path: Path):
    path = tmp_path / "bomb.docx"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", b"0" * (2 * 1024 * 1024))

    with pytest.raises(ValueError, match="压缩比异常"):
        service._validate_docx_archive(path)


def test_docx_archive_rejects_external_entities(tmp_path: Path):
    path = tmp_path / "xxe.docx"
    payload = (
        b'<?xml version="1.0"?>'
        b'<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
        b"<root/>" + b"R" * 200
    )
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", payload)

    with pytest.raises(ValueError, match="外部实体"):
        service._validate_docx_archive(path)


@pytest.mark.asyncio
async def test_file_guard_restores_a_modified_artifact(tmp_path: Path):
    path = tmp_path / "thesis.docx"
    path.write_bytes(b"original")
    guard = ThesisFileGuard([path])
    await guard.snapshot()

    path.write_bytes(b"tampered")
    restored = await guard.verify_and_restore()

    assert restored == [path.name]
    assert path.read_bytes() == b"original"
    await guard.cleanup()

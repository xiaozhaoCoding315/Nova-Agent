"""Document workspace: atomic writes, conflicts, versions, exports."""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest

import app.core.documents.workspace as ws


def _workspace(tmp_path: Path) -> ws.Workspace:
    return ws.create_workspace(tmp_path / "report", title="课程报告", kind="report")


def test_create_workspace_layout_and_master(tmp_path: Path):
    workspace = _workspace(tmp_path)
    assert (workspace.root / "manuscripts" / "main.md").read_text(encoding="utf-8").startswith("# 课程报告")
    for name in ("source", "assets", "exports", ".nova"):
        assert (workspace.root / name).is_dir()
    assert ws.open_workspace(workspace.root).title == "课程报告"


def test_refuses_to_adopt_non_empty_directory(tmp_path: Path):
    target = tmp_path / "busy"
    target.mkdir()
    (target / "important.txt").write_text("do not touch", encoding="utf-8")
    with pytest.raises(ws.WorkspaceError):
        ws.create_workspace(target, title="报告")
    assert (target / "important.txt").read_text(encoding="utf-8") == "do not touch"


def test_write_read_and_conflict_detection(tmp_path: Path):
    workspace = _workspace(tmp_path)
    read = ws.read_manuscript(workspace, "manuscripts/main.md")
    first = ws.write_manuscript(
        workspace, "manuscripts/main.md", "# 课程报告\n\n第一版\n", base_sha=read["sha256"],
    )
    assert first.sha256 and first.version is not None
    assert ws.read_manuscript(workspace, "manuscripts/main.md")["content"].endswith("第一版\n")

    # An external editor changes the file; the stale base must not overwrite it.
    path = workspace.root / "manuscripts" / "main.md"
    path.write_text("# 课程报告\n\n外部修改\n", encoding="utf-8")
    with pytest.raises(ws.WorkspaceConflict):
        ws.write_manuscript(
            workspace, "manuscripts/main.md", "# 覆盖\n", base_sha=first.sha256,
        )
    assert path.read_text(encoding="utf-8").endswith("外部修改\n")

    forced = ws.write_manuscript(workspace, "manuscripts/main.md", "# 覆盖\n", force=True)
    assert forced.created is False
    assert path.read_text(encoding="utf-8") == "# 覆盖\n"


def test_new_file_does_not_need_base_sha(tmp_path: Path):
    workspace = _workspace(tmp_path)
    result = ws.write_manuscript(workspace, "manuscripts/chapter-1.md", "# 第一章\n")
    assert result.created is True
    assert result.version is None


def test_versions_and_restore(tmp_path: Path):
    workspace = _workspace(tmp_path)
    original = ws.read_manuscript(workspace, "manuscripts/main.md")["content"]
    read = ws.read_manuscript(workspace, "manuscripts/main.md")
    ws.write_manuscript(workspace, "manuscripts/main.md", "# 课程报告\n\n第二版\n",
                        base_sha=read["sha256"])

    versions = ws.list_versions(workspace, "manuscripts/main.md")
    assert len(versions) == 1
    snapshot = versions[0]
    assert snapshot.sha256 == hashlib.sha256(original.encode("utf-8")).hexdigest()

    current = ws.read_manuscript(workspace, "manuscripts/main.md")
    restored = ws.restore_version(
        workspace, "manuscripts/main.md", snapshot.version_id, base_sha=current["sha256"],
    )
    assert restored.created is False
    assert ws.read_manuscript(workspace, "manuscripts/main.md")["content"] == original
    # Restoring is a write too, so the replaced revision is still recoverable.
    assert len(ws.list_versions(workspace, "manuscripts/main.md")) == 2


def test_rejects_paths_outside_manuscripts(tmp_path: Path):
    workspace = _workspace(tmp_path)
    for bad in ("../secret.md", "manuscripts/../../secret.md", "/etc/passwd",
                "C:/Windows/win.ini", "assets/note.md", "manuscripts/note.txt"):
        with pytest.raises(ws.WorkspaceError):
            ws.read_manuscript(workspace, bad)


def test_workspace_diagnostics_reports_unsupported_and_tools(tmp_path: Path):
    workspace = _workspace(tmp_path)
    read = ws.read_manuscript(workspace, "manuscripts/main.md")
    ws.write_manuscript(
        workspace, "manuscripts/main.md",
        "# 报告\n\n<div>保留原文</div>\n\n正文\n", base_sha=read["sha256"],
    )
    diagnostics = ws.workspace_diagnostics(workspace)
    assert diagnostics["manuscripts"] == 1
    assert diagnostics["unsupported"].get("html_block") == 1
    assert set(diagnostics["tools"]) == {"pandoc", "libreoffice"}


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="Pandoc is not installed")
def test_export_docx_with_fidelity_sidecar(tmp_path: Path):
    workspace = _workspace(tmp_path)
    read = ws.read_manuscript(workspace, "manuscripts/main.md")
    ws.write_manuscript(
        workspace, "manuscripts/main.md",
        "# 课程报告\n\n## 方法\n\n本文使用 Markdown 作为主控源。\n\n"
        "| 指标 | 数值 |\n| --- | --- |\n| 准确率 | 90% |\n",
        base_sha=read["sha256"],
    )
    result = ws.export_manuscript(workspace, "manuscripts/main.md", "docx")
    assert result.status == "done", result.diagnostics
    assert result.path and result.filename and result.filename.endswith(".docx")
    target = workspace.root / result.path
    assert target.exists() and target.stat().st_size > 0
    assert (workspace.root / result.path).with_suffix(".fidelity.json").exists()

    from docx import Document

    text = "\n".join(paragraph.text for paragraph in Document(str(target)).paragraphs)
    assert "课程报告" in text
    assert "Markdown" in text


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="Pandoc is not installed")
def test_export_reports_lossy_when_markdown_has_unsupported_blocks(tmp_path: Path):
    workspace = _workspace(tmp_path)
    read = ws.read_manuscript(workspace, "manuscripts/main.md")
    ws.write_manuscript(
        workspace, "manuscripts/main.md",
        "# 报告\n\n<div>HTML 块</div>\n\n正文\n", base_sha=read["sha256"],
    )
    result = ws.export_manuscript(workspace, "manuscripts/main.md", "docx")
    assert result.status == "done"
    assert result.fidelity["unsupported"] == ["html_block"]
    assert any("不支持" in note for note in result.fidelity["notes"])


def test_missing_pandoc_is_unsupported_not_failed(tmp_path: Path, monkeypatch):
    workspace = _workspace(tmp_path)
    monkeypatch.setattr(ws, "_tool", lambda _name: None)
    result = ws.export_manuscript(workspace, "manuscripts/main.md", "docx")
    assert result.status == "unsupported"
    assert result.path is None
    assert any("Pandoc" in item for item in result.diagnostics)


def test_missing_libreoffice_is_unsupported_only_for_pdf(tmp_path: Path, monkeypatch):
    real_tool = ws._tool
    monkeypatch.setattr(ws, "_tool", lambda name: None if name in ("soffice", "libreoffice") else real_tool(name))
    if shutil.which("pandoc") is None:
        pytest.skip("Pandoc is not installed")
    workspace = _workspace(tmp_path)
    result = ws.export_manuscript(workspace, "manuscripts/main.md", "pdf")
    assert result.status == "unsupported"
    assert result.format == "pdf"
    assert any("LibreOffice" in item for item in result.diagnostics)

"""Document conversion: profiles, path safety, unsupported tools, fidelity."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from docx import Document

import app.core.documents.convert as convert

PANDOC = shutil.which("pandoc")
needs_pandoc = pytest.mark.skipif(PANDOC is None, reason="Pandoc is not installed")


def _markdown(tmp_path: Path, text: str, name: str = "report.md") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def _plain_markdown(tmp_path: Path) -> Path:
    return _markdown(
        tmp_path,
        "# 课程报告\n\n## 方法\n\n本文使用 Markdown 作为主控源。\n\n"
        "| 指标 | 数值 |\n| --- | --- |\n| 准确率 | 90% |\n\n"
        "脚注[^1]。\n\n[^1]: 脚注内容。\n",
    )


def test_profiles_are_builtin_and_conservative():
    for name in ("report", "thesis", "resume"):
        profile = convert.get_profile(name)
        assert profile.name == name
        assert profile.page_size in ("A4", "Letter")
        assert profile.margin_mm > 0
        assert profile.font
        assert profile.font_size_pt > 0
        assert profile.line_spacing > 0
        assert profile.notes
        assert any("不保证" in note for note in profile.notes)
        assert convert.PROFILES[name] is profile
    assert convert.get_profile(" Report ").name == "report"


def test_unknown_profile_and_target_format_are_rejected(tmp_path: Path):
    with pytest.raises(convert.ConversionError, match="转换配置"):
        convert.get_profile("journal")
    source = _plain_markdown(tmp_path)
    with pytest.raises(convert.ConversionError, match="目标格式"):
        convert.convert_document(source, "rtf", tmp_path / "out")
    with pytest.raises(convert.ConversionError, match="转换配置"):
        convert.convert_document(source, "docx", tmp_path / "out", profile="journal")
    assert not (tmp_path / "out").exists()


def test_pdf_to_docx_is_rejected(tmp_path: Path):
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"%PDF-1.4\n%%EOF\n")
    with pytest.raises(convert.ConversionError) as excinfo:
        convert.convert_document(source, "docx", tmp_path / "out")
    message = str(excinfo.value)
    assert "PDF" in message and "DOCX" in message
    assert not (tmp_path / "out").exists()


def test_output_path_traversal_is_rejected(tmp_path: Path):
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    for bad in ("../escape.docx", "../../escape.docx", "nested/../../escape.docx",
                "/tmp/escape.docx", "C:/Windows/escape.docx"):
        with pytest.raises(convert.ConversionError):
            convert.resolve_output_path(output_dir, bad)
    inside = convert.resolve_output_path(output_dir, "nested/ok.docx")
    assert inside == (output_dir / "nested" / "ok.docx").resolve()


@needs_pandoc
def test_overwrite_is_refused_then_allowed(tmp_path: Path):
    source = _plain_markdown(tmp_path)
    output_dir = tmp_path / "out"
    first = convert.convert_document(source, "docx", output_dir)
    assert first.status == "done", first.diagnostics
    target = Path(first.output_path)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()

    with pytest.raises(convert.ConversionError, match="overwrite"):
        convert.convert_document(source, "docx", output_dir)
    assert hashlib.sha256(target.read_bytes()).hexdigest() == digest

    second = convert.convert_document(source, "docx", output_dir, overwrite=True)
    assert second.status == "done", second.diagnostics
    assert Path(second.output_path) == target
    assert Path(second.fidelity_path).exists()


def test_missing_pandoc_is_unsupported_without_output(tmp_path: Path, monkeypatch):
    source = _plain_markdown(tmp_path)
    output_dir = tmp_path / "out"
    monkeypatch.setattr(convert, "_tool", lambda _name: None)

    result = convert.convert_document(source, "docx", output_dir)

    assert result.status == "unsupported"
    assert result.output_path is None
    assert result.fidelity_path is None
    assert result.fidelity["status"] == "unsupported"
    assert any("Pandoc" in item for item in result.diagnostics)
    assert list(output_dir.glob("*.docx")) == []
    assert not list(output_dir.glob("*.fidelity.json"))


@needs_pandoc
def test_missing_libreoffice_preserves_intermediate_docx(tmp_path: Path, monkeypatch):
    real_tool = convert._tool
    monkeypatch.setattr(
        convert, "_tool",
        lambda name: None if name in ("soffice", "libreoffice") else real_tool(name),
    )
    source = _plain_markdown(tmp_path)
    output_dir = tmp_path / "out"

    result = convert.convert_document(source, "pdf", output_dir)

    assert result.status == "unsupported"
    assert result.output_path is not None
    preserved = Path(result.output_path)
    assert preserved.suffix == ".docx"
    assert preserved.exists() and preserved.stat().st_size > 0
    assert not (output_dir / "report.pdf").exists()
    assert result.fidelity_path is None
    assert result.fidelity["status"] == "unsupported"
    assert any("LibreOffice" in item for item in result.diagnostics)
    assert "report.docx" in result.diagnostics[0]


@needs_pandoc
def test_markdown_to_docx_writes_output_and_fidelity_sidecar(tmp_path: Path):
    source = _plain_markdown(tmp_path)
    output_dir = tmp_path / "out"

    result = convert.convert_document(source, "docx", output_dir, profile="report")

    assert result.status == "done", result.diagnostics
    target = Path(result.output_path)
    sidecar = Path(result.fidelity_path)
    assert target == (output_dir / "report.docx").resolve()
    assert target.exists() and target.stat().st_size > 0
    assert sidecar == (output_dir / "report.docx.fidelity.json").resolve()
    assert sorted(path.name for path in output_dir.iterdir()) == [
        "report.docx", "report.docx.fidelity.json",
    ]

    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    assert payload["source"] == "report.md"
    assert payload["target"] == "report.docx"
    assert payload["profile"] == "report"
    assert payload["status"] == "exact"
    assert "表格" in payload["preserved"]
    assert "脚注" in payload["preserved"]
    assert payload["changed"] == []
    assert payload["dropped"] == []
    assert payload["unsupported"] == []
    assert payload["tool_versions"]["pandoc"]
    assert payload["created_at"]

    document = Document(str(target))
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    assert "课程报告" in text
    assert "准确率" in "\n".join(
        cell.text for table in document.tables for row in table.rows for cell in row.cells
    )
    assert len(document.tables) == 1


@needs_pandoc
def test_profile_layout_is_applied_to_docx(tmp_path: Path):
    source = _plain_markdown(tmp_path)
    output_dir = tmp_path / "out"

    result = convert.convert_document(source, "docx", output_dir, profile="resume")

    assert result.status == "done", result.diagnostics
    document = Document(result.output_path)
    section = document.sections[0]
    assert round(section.page_width.mm) == 210
    assert round(section.page_height.mm) == 297
    assert round(section.left_margin.mm) == 15
    assert document.styles["Normal"].font.name == "微软雅黑"
    assert document.styles["Normal"].font.size.pt == 10.5
    assert result.fidelity["profile"] == "resume"


@needs_pandoc
def test_raw_html_and_math_are_lossy_and_require_opt_in(tmp_path: Path):
    source = _markdown(
        tmp_path,
        "# 报告\n\n<div>HTML 块</div>\n\n公式：$x+y$\n\n$$\na=b\n$$\n\n正文。\n",
    )
    output_dir = tmp_path / "out"

    with pytest.raises(convert.ConversionError, match="allow_lossy"):
        convert.convert_document(source, "docx", output_dir)
    assert not (output_dir / "report.docx").exists()

    result = convert.convert_document(
        source, "docx", output_dir, allow_lossy=True,
    )

    assert result.status == "done", result.diagnostics
    assert result.fidelity["status"] == "lossy"
    assert "html_block" in result.fidelity["unsupported"]
    assert "math_block" in result.fidelity["unsupported"]
    assert any("allow_lossy" in item for item in result.diagnostics)
    assert Path(result.output_path).exists()
    payload = json.loads(Path(result.fidelity_path).read_text(encoding="utf-8"))
    assert payload["status"] == "lossy"


def test_failed_pandoc_leaves_no_partial_output(tmp_path: Path, monkeypatch):
    source = _plain_markdown(tmp_path)
    output_dir = tmp_path / "out"
    monkeypatch.setattr(
        convert, "_tool", lambda name: "pandoc" if name == "pandoc" else None,
    )

    def fake_run(command, *, cwd):
        # Write a partial artifact, then fail like a real tool would.
        output = Path(command[command.index("-o") + 1])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"partial docx")
        return subprocess.CompletedProcess(command, 1, "", "simulated failure")

    monkeypatch.setattr(convert, "_run", fake_run)

    result = convert.convert_document(source, "docx", output_dir)

    assert result.status == "failed"
    assert result.output_path is None
    assert result.fidelity_path is None
    assert result.fidelity["status"] == "unsupported"
    assert any("Pandoc" in item for item in result.diagnostics)
    assert list(output_dir.iterdir()) == []


def test_missing_libreoffice_for_docx_to_pdf_is_unsupported(tmp_path: Path, monkeypatch):
    source = tmp_path / "paper.docx"
    Document().save(str(source))
    output_dir = tmp_path / "out"
    monkeypatch.setattr(convert, "_tool", lambda _name: None)

    result = convert.convert_document(source, "pdf", output_dir)

    assert result.status == "unsupported"
    assert result.output_path is None
    assert result.fidelity_path is None
    assert result.fidelity["status"] == "unsupported"
    assert any("LibreOffice" in item for item in result.diagnostics)
    assert list(output_dir.glob("*.pdf")) == []

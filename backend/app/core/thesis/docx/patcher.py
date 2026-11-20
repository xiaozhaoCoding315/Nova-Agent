"""Conservative, attribute-level DOCX fixes.

The patcher never edits the user's original file.  It writes a new document
and refuses to install anything whose re-parsed content differs from the
source (paragraph/char/image/table counts).  Only the properties named by the
fix payload are touched; body text is never rewritten.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from docx import Document
from docx.document import Document as DocumentType
from docx.oxml.ns import qn
from docx.shared import Cm
from docx.text.paragraph import Paragraph

from app.core.thesis.docx.parser import parse_docx
from app.core.thesis.models import DocumentModel

SUPPORTED_FIX_TYPES = ("set_page_size", "set_margins", "set_heading_style")
VERIFY_KEYS = ("paragraph_count", "table_count", "image_count", "char_count", "word_count")


class FixError(ValueError):
    """Raised when a fix is unsupported or would change document content."""


def _section_at(document: DocumentType, index: int) -> Any:
    sections = document.sections
    if index < 0 or index >= len(sections):
        raise FixError(f"文档没有第 {index + 1} 节，无法修复")
    return sections[index]


def _nth_body_paragraph(document: DocumentType, block_index: int) -> Paragraph:
    position = 0
    for child in document.element.body.iterchildren():
        if child.tag == qn("w:p"):
            if position == block_index:
                return Paragraph(child, document)
            position += 1
        elif child.tag == qn("w:tbl"):
            if position == block_index:
                raise FixError("目标位置是表格，不能套用标题样式")
            position += 1
    raise FixError(f"找不到第 {block_index + 1} 个段落，文档可能已变化")


def _heading_style(document: DocumentType, level: int) -> Any:
    for name in (f"Heading {level}", f"标题 {level}"):
        try:
            return document.styles[name]
        except KeyError:
            continue
    raise FixError(
        f"文档中没有 {level} 级标题样式；请先在 Word 中定义该样式，再重新检查。"
    )


def _apply(document: DocumentType, fix_type: str, payload: dict[str, Any]) -> None:
    if fix_type == "set_page_size":
        section = _section_at(document, int(payload["section_index"]))
        section.page_width = Cm(float(payload["width_cm"]))
        section.page_height = Cm(float(payload["height_cm"]))
    elif fix_type == "set_margins":
        section = _section_at(document, int(payload["section_index"]))
        section.top_margin = Cm(float(payload["top_cm"]))
        section.bottom_margin = Cm(float(payload["bottom_cm"]))
        section.left_margin = Cm(float(payload["left_cm"]))
        section.right_margin = Cm(float(payload["right_cm"]))
    elif fix_type == "set_heading_style":
        paragraph = _nth_body_paragraph(document, int(payload["block_index"]))
        expected = str(payload.get("expected_text") or "").strip()
        if expected and paragraph.text.strip() != expected:
            raise FixError("目标段落内容与检查时不一致，已取消修复；请重新扫描")
        paragraph.style = _heading_style(document, int(payload["level"]))
    else:
        raise FixError(f"不支持的修复类型：{fix_type}")


def _section_snapshot(model: DocumentModel, index: int) -> dict[str, Any]:
    if index < 0 or index >= len(model.sections):
        return {}
    section = model.sections[index]
    return {
        "page_width_cm": section.page_width_cm,
        "page_height_cm": section.page_height_cm,
        "top_margin_cm": section.top_margin_cm,
        "bottom_margin_cm": section.bottom_margin_cm,
        "left_margin_cm": section.left_margin_cm,
        "right_margin_cm": section.right_margin_cm,
    }


def _block_snapshot(model: DocumentModel, index: int) -> dict[str, Any]:
    block = next((item for item in model.blocks if item.index == index), None)
    if block is None:
        return {}
    return {"style": block.style, "text": block.text[:120], "heading_level": block.heading_level}


def verify_same_content(before: DocumentModel, after: DocumentModel) -> list[str]:
    problems: list[str] = []
    for key in VERIFY_KEYS:
        expected = int(before.stats.get(key, 0) or 0)
        actual = int(after.stats.get(key, 0) or 0)
        if expected != actual:
            problems.append(f"{key}: {expected} → {actual}")
    if len(before.blocks) != len(after.blocks):
        problems.append(f"block_count: {len(before.blocks)} → {len(after.blocks)}")
    return problems


def preview_fix(
    source: Path,
    fix_type: str,
    payload: dict[str, Any],
    *,
    before_model: DocumentModel | None = None,
) -> dict[str, Any]:
    """Apply the fix to a temporary copy and verify it; nothing is persisted."""
    if fix_type not in SUPPORTED_FIX_TYPES:
        raise FixError(f"该问题暂不支持自动修复（{fix_type}）")
    before = before_model or parse_docx(source)
    with tempfile.TemporaryDirectory(prefix="nova-thesis-preview-") as tmp:
        patched_path = Path(tmp) / "patched.docx"
        document = Document(str(source))
        _apply(document, fix_type, payload)
        document.save(str(patched_path))
        after = parse_docx(
            patched_path,
            filename=before.filename,
            sha256=before.sha256,
            size=before.size,
        )
    problems = verify_same_content(before, after)
    if problems:
        raise FixError("修复会改变文档内容，已取消：" + "；".join(problems))
    section_index = int(payload.get("section_index", -1))
    block_index = int(payload.get("block_index", -1))
    return {
        "fix_type": fix_type,
        "payload": payload,
        "before": (
            _section_snapshot(before, section_index)
            if section_index >= 0
            else _block_snapshot(before, block_index)
        ),
        "after": (
            _section_snapshot(after, section_index)
            if section_index >= 0
            else _block_snapshot(after, block_index)
        ),
        "verification": {
            "ok": True,
            **{key: int(after.stats.get(key, 0) or 0) for key in VERIFY_KEYS},
        },
        "note": "预览只生成临时副本，没有改动任何文件。",
    }


def apply_fix_file(
    source: Path,
    destination: Path,
    fix_type: str,
    payload: dict[str, Any],
    *,
    before_model: DocumentModel | None = None,
) -> dict[str, Any]:
    """Write the patched document to ``destination`` and verify it.

    ``destination`` is a temporary path chosen by the caller; the caller must
    only promote it to the working document after this function returns.
    """
    if fix_type not in SUPPORTED_FIX_TYPES:
        raise FixError(f"该问题暂不支持自动修复（{fix_type}）")
    before = before_model or parse_docx(source)
    document = Document(str(source))
    _apply(document, fix_type, payload)
    document.save(str(destination))
    after = parse_docx(
        destination,
        filename=before.filename,
        sha256=before.sha256,
        size=before.size,
    )
    problems = verify_same_content(before, after)
    if problems:
        destination.unlink(missing_ok=True)
        raise FixError("修复会改变文档内容，已取消：" + "；".join(problems))
    return {"model": after, "verification": {"ok": True, "problems": []}}

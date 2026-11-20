"""Deterministic DOCX -> DocumentModel parser.

The parser never modifies the source file.  It walks the OOXML body in order
so paragraphs and tables keep their original sequence, and records the style
information the rule engine needs (sections, margins, heading styles,
paragraph formatting, table dimensions).
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from docx import Document
from docx.document import Document as DocumentType
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.core.thesis.models import PARSER_VERSION, Block, DocumentModel, SectionInfo

HEADING_RE = re.compile(r"^(?:heading|标题)\s*([1-9]\d*)$", re.IGNORECASE)
NUMBERED_HEADING_RE = re.compile(r"^\d+(?:\.\d+)+\s+\S")
MAX_BLOCK_TEXT = 20_000
MAX_TABLE_PREVIEW_ROWS = 30


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _cm(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value.cm), 3)
    except (AttributeError, TypeError, ValueError):
        return None


def _pt(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value.pt), 2)
    except (AttributeError, TypeError, ValueError):
        return None


def _enum_name(value: Any) -> str | None:
    if value is None:
        return None
    name = getattr(value, "name", None)
    if name:
        return str(name)
    text = str(value)
    return text.rsplit(".", 1)[-1] if text else None


def _style_name(style: Any) -> str:
    return str(getattr(style, "name", "") or "")


def _heading_level(paragraph: Paragraph) -> int | None:
    match = HEADING_RE.match(_style_name(paragraph.style).strip())
    if match:
        return int(match.group(1))
    p_pr = paragraph._p.pPr
    if p_pr is not None:
        outline = p_pr.find(qn("w:outlineLvl"))
        if outline is not None:
            raw = outline.get(qn("w:val"))
            if raw is not None and raw.isdigit():
                return int(raw) + 1
    return None


def _run_font(run: Any) -> tuple[float | None, str | None]:
    size = _pt(run.font.size)
    name = run.font.name
    r_pr = run._element.rPr
    if r_pr is not None:
        r_fonts = r_pr.find(qn("w:rFonts"))
        if r_fonts is not None:
            name = (
                r_fonts.get(qn("w:eastAsia"))
                or r_fonts.get(qn("w:ascii"))
                or name
            )
    return size, name


def _paragraph_font(paragraph: Paragraph) -> tuple[float | None, str | None, bool | None]:
    for run in paragraph.runs:
        if run.text.strip():
            size, name = _run_font(run)
            return size, name, run.bold
    style = paragraph.style
    if style is None:
        return None, None, None
    size = _pt(getattr(style.font, "size", None))
    name = getattr(style.font, "name", None)
    return size, name, getattr(style.font, "bold", None)


def _line_spacing(paragraph: Paragraph) -> float | None:
    value = paragraph.paragraph_format.line_spacing
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _has_section_break(paragraph: Paragraph) -> bool:
    p_pr = paragraph._p.pPr
    return p_pr is not None and p_pr.find(qn("w:sectPr")) is not None


def _count_page_breaks(element: Any) -> int:
    count = 0
    for br in element.iter(qn("w:br")):
        if br.get(qn("w:type")) == "page":
            count += 1
    return count


PAGE_FIELD_RE = re.compile(r"\bPAGE\b")


def _header_footer_parts(section: Any) -> list[Any]:
    parts: list[Any] = []
    for attribute in (
        "header", "footer",
        "even_page_header", "even_page_footer",
        "first_page_header", "first_page_footer",
    ):
        try:
            parts.append(getattr(section, attribute))
        except (AttributeError, ValueError):
            continue
    return parts


def _part_text(part: Any) -> str:
    try:
        return "\n".join(
            paragraph.text.strip()
            for paragraph in part.paragraphs
            if paragraph.text.strip()
        )[:500]
    except (AttributeError, ValueError):
        return ""


def _part_has_page_field(part: Any) -> bool:
    element = getattr(part, "_element", None)
    if element is None:
        return False
    for instruction in element.iter(qn("w:instrText")):
        if PAGE_FIELD_RE.search((instruction.text or "").upper()):
            return True
    for field in element.iter(qn("w:fldSimple")):
        if PAGE_FIELD_RE.search((field.get(qn("w:instr")) or "").upper()):
            return True
    return False


def _section_info(index: int, section: Any) -> SectionInfo:
    parts = _header_footer_parts(section)
    header_texts: list[str] = []
    footer_texts: list[str] = []
    for attribute, bucket in (
        ("header", header_texts),
        ("first_page_header", header_texts),
        ("even_page_header", header_texts),
        ("footer", footer_texts),
        ("first_page_footer", footer_texts),
        ("even_page_footer", footer_texts),
    ):
        try:
            text = _part_text(getattr(section, attribute))
        except (AttributeError, ValueError):
            continue
        if text:
            bucket.append(text)
    return SectionInfo(
        index=index,
        page_width_cm=_cm(section.page_width) or 0.0,
        page_height_cm=_cm(section.page_height) or 0.0,
        top_margin_cm=_cm(section.top_margin) or 0.0,
        bottom_margin_cm=_cm(section.bottom_margin) or 0.0,
        left_margin_cm=_cm(section.left_margin) or 0.0,
        right_margin_cm=_cm(section.right_margin) or 0.0,
        header_distance_cm=_cm(section.header_distance) or 0.0,
        footer_distance_cm=_cm(section.footer_distance) or 0.0,
        orientation=_enum_name(section.orientation) or "PORTRAIT",
        start_type=_enum_name(section.start_type) or "NEW_PAGE",
        header_text=" / ".join(dict.fromkeys(header_texts)),
        footer_text=" / ".join(dict.fromkeys(footer_texts)),
        has_page_number=any(_part_has_page_field(part) for part in parts),
    )


def _paragraph_block(index: int, paragraph: Paragraph, section_index: int) -> Block:
    text = paragraph.text.strip()
    level = _heading_level(paragraph)
    font_size, font_name, bold = _paragraph_font(paragraph)
    return Block(
        index=index,
        kind="paragraph",
        style=_style_name(paragraph.style),
        text=text[:MAX_BLOCK_TEXT],
        heading_level=level,
        section_index=section_index,
        alignment=_enum_name(paragraph.alignment),
        first_line_indent_cm=_cm(paragraph.paragraph_format.first_line_indent),
        line_spacing=_line_spacing(paragraph),
        font_size_pt=font_size,
        font_name=font_name,
        bold=bold,
        page_break_before=bool(paragraph.paragraph_format.page_break_before),
    )


def _table_block(index: int, table: Table, section_index: int) -> Block:
    rows = len(table.rows)
    cols = len(table.columns)
    preview: list[str] = []
    for row in table.rows[:MAX_TABLE_PREVIEW_ROWS]:
        cells = [" ".join(cell.text.split()) for cell in row.cells]
        preview.append(" | ".join(cells))
    return Block(
        index=index,
        kind="table",
        style=_style_name(getattr(table, "style", None)),
        text="\n".join(preview)[:MAX_BLOCK_TEXT],
        section_index=section_index,
        rows=rows,
        cols=cols,
    )


def _document_stats(document: DocumentType, blocks: list[Block], outline: list[dict[str, Any]]) -> dict[str, Any]:
    paragraphs = [block for block in blocks if block.kind == "paragraph"]
    text = "\n".join(block.text for block in paragraphs)
    chinese_chars = len(re.findall(r"[一-鿿]", text))
    latin_words = len(re.findall(r"[A-Za-z0-9]+", text))
    return {
        "block_count": len(blocks),
        "paragraph_count": len(paragraphs),
        "table_count": sum(1 for block in blocks if block.kind == "table"),
        "heading_count": len(outline),
        "max_heading_level": max((int(item["level"]) for item in outline), default=0),
        "char_count": len(text.replace("\n", "")),
        "word_count": chinese_chars + latin_words,
        "image_count": len(document.inline_shapes),
        "section_count": len(document.sections),
        "page_break_count": sum(
            _count_page_breaks(block_element)
            for block_element in document.element.body.iterchildren()
        ),
        "empty_paragraph_count": sum(1 for block in paragraphs if not block.text),
        "has_toc": any("目录" in block.text for block in paragraphs),
    }


def parse_docx(
    path: Path,
    *,
    filename: str | None = None,
    sha256: str | None = None,
    size: int | None = None,
    max_blocks: int = 5000,
) -> DocumentModel:
    """Parse one DOCX into a JSON-serialisable document model."""
    document = Document(str(path))
    sections = [_section_info(index, section) for index, section in enumerate(document.sections)]
    blocks: list[Block] = []
    outline: list[dict[str, Any]] = []
    warnings: list[str] = []
    section_index = 0

    for child in document.element.body.iterchildren():
        if len(blocks) >= max_blocks:
            warnings.append(f"文档超过 {max_blocks} 个块，后续内容未纳入模型")
            break
        if child.tag == qn("w:p"):
            paragraph = Paragraph(child, document)
            block = _paragraph_block(len(blocks), paragraph, section_index)
            blocks.append(block)
            if block.heading_level is not None and block.text:
                outline.append({
                    "level": block.heading_level,
                    "text": block.text,
                    "block_index": block.index,
                    "style": block.style,
                })
            if _has_section_break(paragraph):
                section_index += 1
        elif child.tag == qn("w:tbl"):
            table = Table(child, document)
            blocks.append(_table_block(len(blocks), table, section_index))

    stats = _document_stats(document, blocks, outline)
    if not outline:
        warnings.append("未检测到标题样式：目录与层级检查无法进行")
    if stats["table_count"]:
        warnings.append("M0 只解析表格结构，表格内格式检查将在后续版本加入")
    if sha256 is None or size is None:
        real_path = Path(path)
        sha256 = sha256 or file_sha256(real_path)
        size = size if size is not None else real_path.stat().st_size

    return DocumentModel(
        filename=filename or Path(path).name,
        sha256=sha256,
        size=int(size),
        sections=sections,
        blocks=blocks,
        outline=outline,
        stats=stats,
        warnings=warnings,
        parser_version=PARSER_VERSION,
    )

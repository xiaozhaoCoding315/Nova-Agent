"""A deliberately small Markdown -> DocumentIR reader.

M1 only needs a real, testable contract; the full adapter (templates, styles,
Pandoc, DOCX export) lands in M2.  This reader supports the common block and
inline constructs used by reports and resumes, and records everything it does
not understand as an ``unsupported`` diagnostic instead of silently dropping
it.
"""
from __future__ import annotations

import hashlib
import re
from typing import Iterable

from app.core.documents.ir import (
    Block,
    Diagnostic,
    DocumentIR,
    Inline,
    SourceLocator,
)

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_IMAGE_BLOCK = re.compile(r"^\s*!\[([^\]]*)\]\(([^)]+)\)\s*$")
_LIST_ITEM = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$")
_THEMATIC = re.compile(r"^\s*([-*_])(?:\s*\1){2,}\s*$")
_TABLE_SEPARATOR = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$")
_HTML_START = re.compile(r"^\s*<(?:!doctype|html|div|table|p|span|br|h[1-6]|ul|ol|li)\b", re.I)
_FOOTNOTE = re.compile(r"^\s*\[\^[^\]]+\]:")
_MATH_FENCE = re.compile(r"^\s*\$\$\s*$")


def _text_hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _locator(path: str, line: int, block_index: int) -> SourceLocator:
    return SourceLocator(
        kind="markdown",
        path=path,
        line=line,
        column=1,
        block_index=block_index,
    )


def _inline(text: str) -> list[Inline]:
    """Parse the small inline subset; unknown markup stays literal text."""
    result: list[Inline] = []
    index = 0
    length = len(text)
    while index < length:
        if text.startswith("**", index):
            end = text.find("**", index + 2)
            if end > index + 2:
                result.append(Inline(kind="strong", text=text[index + 2:end]))
                index = end + 2
                continue
        if text.startswith("__", index):
            end = text.find("__", index + 2)
            if end > index + 2:
                result.append(Inline(kind="strong", text=text[index + 2:end]))
                index = end + 2
                continue
        if text[index] in "*_":
            end = text.find(text[index], index + 1)
            if end > index + 1:
                result.append(Inline(kind="emphasis", text=text[index + 1:end]))
                index = end + 1
                continue
        if text[index] == "`":
            end = text.find("`", index + 1)
            if end > index:
                result.append(Inline(kind="code", text=text[index + 1:end]))
                index = end + 1
                continue
        if text.startswith("![", index):
            match = re.match(r"!\[([^\]]*)\]\(([^)]+)\)", text[index:])
            if match:
                result.append(Inline(
                    kind="image",
                    text=match.group(1),
                    target=match.group(2),
                ))
                index += match.end()
                continue
        if text[index] == "[":
            match = re.match(r"\[([^\]]+)\]\(([^)]+)\)", text[index:])
            if match:
                result.append(Inline(
                    kind="link",
                    text=match.group(1),
                    target=match.group(2),
                ))
                index += match.end()
                continue
        next_special = length
        for marker in ("**", "__", "*", "_", "`", "![", "["):
            found = text.find(marker, index + 1)
            if found != -1:
                next_special = min(next_special, found)
        result.append(Inline(kind="text", text=text[index:next_special]))
        index = next_special
    return _merge_text(result)


def _merge_text(items: Iterable[Inline]) -> list[Inline]:
    merged: list[Inline] = []
    for item in items:
        if (
            item.kind == "text"
            and merged
            and merged[-1].kind == "text"
        ):
            merged[-1].text += item.text
        else:
            merged.append(item)
    return merged


def _split_table_row(line: str) -> list[list[Inline]]:
    raw = line.strip()
    if raw.startswith("|"):
        raw = raw[1:]
    if raw.endswith("|"):
        raw = raw[:-1]
    return [_inline(cell.strip()) for cell in raw.split("|")]


def _line_starts_block(line: str, next_line: str = "") -> bool:
    return bool(
        _HEADING.match(line)
        or _LIST_ITEM.match(line)
        or _THEMATIC.match(line)
        or line.lstrip().startswith(("```", "~~~", ">", "|"))
        or _IMAGE_BLOCK.match(line)
        or _HTML_START.match(line)
        or _FOOTNOTE.match(line)
        or _MATH_FENCE.match(line)
        or (next_line and _TABLE_SEPARATOR.match(next_line))
    )


def parse_markdown(
    text: str,
    *,
    document_id: str = "doc",
    kind: str = "report",
    path: str = "",
    title: str = "",
) -> DocumentIR:
    """Parse Markdown into the shared IR.

    Unsupported constructs are preserved as plain text and recorded with an
    ``unsupported`` diagnostic.  The parser never silently discards content.
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: list[Block] = []
    diagnostics: list[Diagnostic] = []

    def add_block(block: Block) -> None:
        block.source = block.source or _locator(path, 0, len(blocks))
        block.source.block_index = len(blocks)
        block.source.content_hash = _text_hash(block.plain_text())
        blocks.append(block)

    def unsupported(code: str, message: str, line_no: int, content: str) -> None:
        diagnostics.append(Diagnostic(
            severity="unsupported",
            code=code,
            message=message,
            locator=_locator(path, line_no, len(blocks)),
        ))
        add_block(Block(
            id=f"b{len(blocks) + 1}",
            kind="paragraph",
            text=content,
            source=_locator(path, line_no, len(blocks)),
            diagnostics=[Diagnostic(
                severity="unsupported",
                code=code,
                message=message,
            )],
        ))

    index = 0
    while index < len(lines):
        line = lines[index]
        line_no = index + 1
        if not line.strip():
            index += 1
            continue

        heading = _HEADING.match(line)
        if heading:
            add_block(Block(
                id=f"b{len(blocks) + 1}",
                kind="heading",
                text=heading.group(2).strip(),
                inlines=_inline(heading.group(2).strip()),
                level=len(heading.group(1)),
                source=_locator(path, line_no, len(blocks)),
            ))
            index += 1
            continue

        image = _IMAGE_BLOCK.match(line)
        if image:
            add_block(Block(
                id=f"b{len(blocks) + 1}",
                kind="image",
                text=image.group(1),
                attrs={"target": image.group(2), "alt_text": image.group(1)},
                source=_locator(path, line_no, len(blocks)),
            ))
            index += 1
            continue

        fence = line.lstrip()
        if fence.startswith("```") or fence.startswith("~~~"):
            marker = fence[:3]
            language = fence[3:].strip()
            body: list[str] = []
            index += 1
            while index < len(lines) and not lines[index].lstrip().startswith(marker):
                body.append(lines[index])
                index += 1
            if index < len(lines):
                index += 1
            add_block(Block(
                id=f"b{len(blocks) + 1}",
                kind="code",
                text="\n".join(body),
                attrs={"language": language} if language else {},
                source=_locator(path, line_no, len(blocks)),
            ))
            continue

        if _THEMATIC.match(line):
            add_block(Block(
                id=f"b{len(blocks) + 1}",
                kind="thematic_break",
                source=_locator(path, line_no, len(blocks)),
            ))
            index += 1
            continue

        if _HTML_START.match(line):
            buffer = [line]
            index += 1
            while index < len(lines) and lines[index].strip():
                buffer.append(lines[index])
                index += 1
            unsupported(
                "html_block",
                "HTML blocks are preserved as plain text; styling and scripts are not imported.",
                line_no,
                "\n".join(buffer),
            )
            continue

        if _FOOTNOTE.match(line):
            buffer = [line]
            index += 1
            while index < len(lines) and lines[index].startswith("    "):
                buffer.append(lines[index])
                index += 1
            unsupported(
                "footnote",
                "Footnote syntax is preserved as plain text; footnote semantics are not imported.",
                line_no,
                "\n".join(buffer),
            )
            continue

        if _MATH_FENCE.match(line):
            buffer = [line]
            index += 1
            while index < len(lines) and not _MATH_FENCE.match(lines[index]):
                buffer.append(lines[index])
                index += 1
            if index < len(lines):
                buffer.append(lines[index])
                index += 1
            unsupported(
                "math_block",
                "Math blocks are preserved as plain text; formula rendering is not imported.",
                line_no,
                "\n".join(buffer),
            )
            continue

        if line.lstrip().startswith(">"):
            buffer = []
            while index < len(lines) and lines[index].lstrip().startswith(">"):
                buffer.append(re.sub(r"^\s*>\s?", "", lines[index]))
                index += 1
            add_block(Block(
                id=f"b{len(blocks) + 1}",
                kind="quote",
                text="\n".join(buffer),
                inlines=_inline(" ".join(buffer)),
                source=_locator(path, line_no, len(blocks)),
            ))
            continue

        item = _LIST_ITEM.match(line)
        if item:
            ordered = item.group(2)[0].isdigit()
            items: list[list[Inline]] = []
            item_lines: list[int] = []
            while index < len(lines):
                current = _LIST_ITEM.match(lines[index])
                if not current:
                    break
                if bool(current.group(2)[0].isdigit()) != ordered:
                    break
                if current.group(1):
                    diagnostics.append(Diagnostic(
                        severity="warning",
                        code="nested_list_flattened",
                        message="Nested list indentation is flattened in M1.",
                        block_id=f"b{len(blocks) + 1}",
                        locator=_locator(path, index + 1, len(blocks)),
                    ))
                items.append(_inline(current.group(3).strip()))
                item_lines.append(index + 1)
                index += 1
            add_block(Block(
                id=f"b{len(blocks) + 1}",
                kind="list",
                items=items,
                attrs={"ordered": ordered},
                source=_locator(path, item_lines[0] if item_lines else line_no, len(blocks)),
            ))
            continue

        if "|" in line and index + 1 < len(lines) and _TABLE_SEPARATOR.match(lines[index + 1]):
            header = _split_table_row(line)
            index += 2
            rows = [header]
            while index < len(lines) and "|" in lines[index] and lines[index].strip():
                rows.append(_split_table_row(lines[index]))
                index += 1
            add_block(Block(
                id=f"b{len(blocks) + 1}",
                kind="table",
                rows=rows,
                source=_locator(path, line_no, len(blocks)),
                diagnostics=[Diagnostic(
                    severity="warning",
                    code="table_style_not_preserved",
                    message="Table cell text is preserved; table styling is adapter-specific.",
                )],
            ))
            continue

        buffer = [line.strip()]
        index += 1
        while index < len(lines) and lines[index].strip():
            if _line_starts_block(lines[index], lines[index + 1] if index + 1 < len(lines) else ""):
                break
            buffer.append(lines[index].strip())
            index += 1
        paragraph_text = "\n".join(buffer)
        add_block(Block(
            id=f"b{len(blocks) + 1}",
            kind="paragraph",
            text=paragraph_text,
            inlines=_inline(paragraph_text),
            source=_locator(path, line_no, len(blocks)),
        ))

    return DocumentIR(
        document_id=document_id,
        kind=kind,
        title=title,
        blocks=blocks,
        diagnostics=diagnostics,
        metadata={"source_format": "markdown", "source_path": path},
    )

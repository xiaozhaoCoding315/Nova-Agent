"""Data structures shared by the thesis parser, rules and API."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Any, Literal

Severity = Literal["blocker", "warn", "info"]
PARSER_VERSION = "m1.0"


@dataclass
class SectionInfo:
    """One Word section (page size, margins, orientation)."""

    index: int
    page_width_cm: float = 0.0
    page_height_cm: float = 0.0
    top_margin_cm: float = 0.0
    bottom_margin_cm: float = 0.0
    left_margin_cm: float = 0.0
    right_margin_cm: float = 0.0
    header_distance_cm: float = 0.0
    footer_distance_cm: float = 0.0
    orientation: str = "PORTRAIT"
    start_type: str = "NEW_PAGE"
    header_text: str = ""
    footer_text: str = ""
    has_page_number: bool = False


@dataclass
class Block:
    """A paragraph or table in document order."""

    index: int
    kind: str = "paragraph"          # paragraph | table
    style: str = ""
    text: str = ""
    heading_level: int | None = None
    section_index: int = 0
    alignment: str | None = None
    first_line_indent_cm: float | None = None
    line_spacing: float | None = None
    font_size_pt: float | None = None
    font_name: str | None = None
    bold: bool | None = None
    page_break_before: bool = False
    rows: int | None = None
    cols: int | None = None


@dataclass
class DocumentModel:
    """The source-of-truth representation we keep for one DOCX."""

    filename: str
    sha256: str
    size: int
    sections: list[SectionInfo] = field(default_factory=list)
    blocks: list[Block] = field(default_factory=list)
    outline: list[dict[str, Any]] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    parser_version: str = PARSER_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DocumentModel":
        def keep(model_cls, payload: dict[str, Any]) -> dict[str, Any]:
            names = {item.name for item in fields(model_cls)}
            return {key: value for key, value in (payload or {}).items() if key in names}

        return cls(
            filename=str(data.get("filename") or ""),
            sha256=str(data.get("sha256") or ""),
            size=int(data.get("size") or 0),
            sections=[SectionInfo(**keep(SectionInfo, item)) for item in data.get("sections", [])],
            blocks=[Block(**keep(Block, item)) for item in data.get("blocks", [])],
            outline=list(data.get("outline") or []),
            stats=dict(data.get("stats") or {}),
            warnings=list(data.get("warnings") or []),
            parser_version=str(data.get("parser_version") or PARSER_VERSION),
        )

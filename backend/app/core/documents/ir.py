"""Document IR, change sets, versions and fidelity contracts.

The IR is a shared *operation language*, not a claim that every format can be
represented losslessly.  Format adapters must report what they preserved,
modified, dropped or do not support.  Existing DOCX files are projected into
this IR for inspection and point patches; the original OOXML package remains
the source of truth (see ``docs/PRODUCT-UPGRADE-ROADMAP.md`` §5.2).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

SCHEMA_VERSION = "doc-ir-1.0"

Severity = Literal["info", "warning", "error", "unsupported"]
BlockKind = Literal[
    "heading", "paragraph", "list", "table", "image", "code",
    "quote", "thematic_break", "section_break", "page_break",
]
InlineKind = Literal[
    "text", "emphasis", "strong", "code", "link", "citation", "math", "image",
]
ChangeOp = Literal["insert", "update", "delete", "move", "style", "asset"]
DiagnosticSeverity = Severity


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_jsonable(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, list):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _to_jsonable(item) for key, item in value.items()}
    return value


def _canonical_hash(payload: Any) -> str:
    raw = json.dumps(
        _to_jsonable(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass
class SourceLocator:
    """Where a block/inline came from, so patches can be traced back."""

    kind: str = "generated"          # markdown | docx | pdf | generated
    path: str = ""
    line: int | None = None
    column: int | None = None
    page: int | None = None
    block_index: int | None = None
    native_path: str = ""           # OOXML XPath / PDF text span, when known
    content_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "path": self.path,
            "line": self.line,
            "column": self.column,
            "page": self.page,
            "block_index": self.block_index,
            "native_path": self.native_path,
            "content_hash": self.content_hash,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "SourceLocator":
        data = data or {}
        return cls(
            kind=str(data.get("kind") or "generated"),
            path=str(data.get("path") or ""),
            line=data.get("line"),
            column=data.get("column"),
            page=data.get("page"),
            block_index=data.get("block_index"),
            native_path=str(data.get("native_path") or ""),
            content_hash=str(data.get("content_hash") or ""),
        )


@dataclass
class Diagnostic:
    """A visible warning about unsupported or lossy content."""

    severity: DiagnosticSeverity = "info"
    code: str = ""
    message: str = ""
    block_id: str = ""
    locator: SourceLocator | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "block_id": self.block_id,
            "locator": _to_jsonable(self.locator) if self.locator else None,
            "details": _to_jsonable(self.details),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "Diagnostic":
        data = data or {}
        locator = data.get("locator")
        return cls(
            severity=str(data.get("severity") or "info"),  # type: ignore[arg-type]
            code=str(data.get("code") or ""),
            message=str(data.get("message") or ""),
            block_id=str(data.get("block_id") or ""),
            locator=SourceLocator.from_dict(locator) if locator else None,
            details=dict(data.get("details") or {}),
        )


@dataclass
class Inline:
    """A run of inline content inside a block."""

    kind: InlineKind = "text"
    text: str = ""
    target: str = ""
    children: list["Inline"] = field(default_factory=list)
    attrs: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "text": self.text,
            "target": self.target,
            "children": [_to_jsonable(child) for child in self.children],
            "attrs": _to_jsonable(self.attrs),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "Inline":
        data = data or {}
        return cls(
            kind=str(data.get("kind") or "text"),  # type: ignore[arg-type]
            text=str(data.get("text") or ""),
            target=str(data.get("target") or ""),
            children=[cls.from_dict(item) for item in data.get("children", [])],
            attrs=dict(data.get("attrs") or {}),
        )

    def plain_text(self) -> str:
        if self.kind == "text" or not self.children:
            return self.text
        return self.text + "".join(child.plain_text() for child in self.children)


@dataclass
class Block:
    """One semantic block in document order."""

    id: str
    kind: BlockKind = "paragraph"
    text: str = ""
    inlines: list[Inline] = field(default_factory=list)
    level: int | None = None
    style: str = ""
    items: list[list[Inline]] = field(default_factory=list)
    rows: list[list[list[Inline]]] = field(default_factory=list)
    children: list["Block"] = field(default_factory=list)
    source: SourceLocator | None = None
    diagnostics: list[Diagnostic] = field(default_factory=list)
    attrs: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "text": self.text,
            "inlines": [_to_jsonable(inline) for inline in self.inlines],
            "level": self.level,
            "style": self.style,
            "items": [
                [_to_jsonable(inline) for inline in item] for item in self.items
            ],
            "rows": [
                [[_to_jsonable(inline) for inline in cell] for cell in row]
                for row in self.rows
            ],
            "children": [_to_jsonable(child) for child in self.children],
            "source": _to_jsonable(self.source) if self.source else None,
            "diagnostics": [_to_jsonable(item) for item in self.diagnostics],
            "attrs": _to_jsonable(self.attrs),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "Block":
        data = data or {}
        source = data.get("source")
        return cls(
            id=str(data.get("id") or ""),
            kind=str(data.get("kind") or "paragraph"),  # type: ignore[arg-type]
            text=str(data.get("text") or ""),
            inlines=[
                Inline.from_dict(inline) for inline in data.get("inlines", [])
            ],
            level=data.get("level"),
            style=str(data.get("style") or ""),
            items=[
                [Inline.from_dict(inline) for inline in item]
                for item in data.get("items", [])
            ],
            rows=[
                [[Inline.from_dict(inline) for inline in cell] for cell in row]
                for row in data.get("rows", [])
            ],
            children=[cls.from_dict(child) for child in data.get("children", [])],
            source=SourceLocator.from_dict(source) if source else None,
            diagnostics=[
                Diagnostic.from_dict(item) for item in data.get("diagnostics", [])
            ],
            attrs=dict(data.get("attrs") or {}),
        )

    def plain_text(self) -> str:
        if self.inlines:
            return "".join(inline.plain_text() for inline in self.inlines)
        if self.kind == "list":
            return "\n".join(
                "".join(inline.plain_text() for inline in item)
                for item in self.items
            )
        if self.kind == "table":
            return "\n".join(
                " | ".join("".join(inline.plain_text() for inline in cell) for cell in row)
                for row in self.rows
            )
        if self.children:
            return "\n".join(child.plain_text() for child in self.children)
        return self.text


@dataclass
class Asset:
    """A binary or external resource referenced by the document."""

    id: str
    path: str = ""
    sha256: str = ""
    role: str = "image"             # image | data | reference | attachment
    alt_text: str = ""
    source: SourceLocator | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "path": self.path,
            "sha256": self.sha256,
            "role": self.role,
            "alt_text": self.alt_text,
            "source": _to_jsonable(self.source) if self.source else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "Asset":
        data = data or {}
        source = data.get("source")
        return cls(
            id=str(data.get("id") or ""),
            path=str(data.get("path") or ""),
            sha256=str(data.get("sha256") or ""),
            role=str(data.get("role") or "image"),
            alt_text=str(data.get("alt_text") or ""),
            source=SourceLocator.from_dict(source) if source else None,
        )


@dataclass
class DocumentIR:
    """The shared representation of one document."""

    document_id: str
    kind: str = "report"            # thesis | report | resume | generic
    title: str = ""
    locale: str = "zh-CN"
    schema_version: str = SCHEMA_VERSION
    source_revision: str = ""
    template_version: str = ""
    blocks: list[Block] = field(default_factory=list)
    assets: list[Asset] = field(default_factory=list)
    styles: dict[str, Any] = field(default_factory=dict)
    sections: list[dict[str, Any]] = field(default_factory=list)
    references: list[dict[str, Any]] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "document_id": self.document_id,
            "kind": self.kind,
            "title": self.title,
            "locale": self.locale,
            "source_revision": self.source_revision,
            "template_version": self.template_version,
            "blocks": [_to_jsonable(block) for block in self.blocks],
            "assets": [_to_jsonable(asset) for asset in self.assets],
            "styles": _to_jsonable(self.styles),
            "sections": _to_jsonable(self.sections),
            "references": _to_jsonable(self.references),
            "diagnostics": [_to_jsonable(item) for item in self.diagnostics],
            "metadata": _to_jsonable(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "DocumentIR":
        data = data or {}
        version = str(data.get("schema_version") or "")
        if version and version != SCHEMA_VERSION:
            raise ValueError(
                f"unsupported document schema_version: {version!r}; "
                f"expected {SCHEMA_VERSION!r}"
            )
        return cls(
            document_id=str(data.get("document_id") or ""),
            kind=str(data.get("kind") or "report"),
            title=str(data.get("title") or ""),
            locale=str(data.get("locale") or "zh-CN"),
            schema_version=SCHEMA_VERSION,
            source_revision=str(data.get("source_revision") or ""),
            template_version=str(data.get("template_version") or ""),
            blocks=[Block.from_dict(item) for item in data.get("blocks", [])],
            assets=[Asset.from_dict(item) for item in data.get("assets", [])],
            styles=dict(data.get("styles") or {}),
            sections=list(data.get("sections") or []),
            references=list(data.get("references") or []),
            diagnostics=[
                Diagnostic.from_dict(item) for item in data.get("diagnostics", [])
            ],
            metadata=dict(data.get("metadata") or {}),
        )

    def content_hash(self) -> str:
        payload = {
            "schema_version": self.schema_version,
            "document_id": self.document_id,
            "kind": self.kind,
            "title": self.title,
            "locale": self.locale,
            "blocks": self.blocks,
            "assets": self.assets,
            "styles": self.styles,
            "sections": self.sections,
            "references": self.references,
        }
        return _canonical_hash(payload)

    def plain_text(self) -> str:
        return "\n\n".join(block.plain_text() for block in self.blocks)

    def unsupported_diagnostics(self) -> list[Diagnostic]:
        return [
            item for item in self.diagnostics
            if item.severity == "unsupported"
        ]

    def block_by_id(self, block_id: str) -> Block | None:
        for block in self.blocks:
            if block.id == block_id:
                return block
        return None


@dataclass
class ChangeOperation:
    """One atomic change against a block or asset."""

    op: ChangeOp
    target_id: str
    before_hash: str = ""
    after_hash: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    source: SourceLocator | None = None
    diagnostics: list[Diagnostic] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "op": self.op,
            "target_id": self.target_id,
            "before_hash": self.before_hash,
            "after_hash": self.after_hash,
            "payload": _to_jsonable(self.payload),
            "source": _to_jsonable(self.source) if self.source else None,
            "diagnostics": [_to_jsonable(item) for item in self.diagnostics],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ChangeOperation":
        data = data or {}
        source = data.get("source")
        return cls(
            op=str(data.get("op") or "update"),  # type: ignore[arg-type]
            target_id=str(data.get("target_id") or ""),
            before_hash=str(data.get("before_hash") or ""),
            after_hash=str(data.get("after_hash") or ""),
            payload=dict(data.get("payload") or {}),
            source=SourceLocator.from_dict(source) if source else None,
            diagnostics=[
                Diagnostic.from_dict(item) for item in data.get("diagnostics", [])
            ],
        )


@dataclass
class ChangeSet:
    """A reviewable set of changes bound to a base document hash."""

    change_id: str
    base_hash: str
    target_hash: str = ""
    operations: list[ChangeOperation] = field(default_factory=list)
    created_at: str = field(default_factory=_utc_now)
    author: str = ""
    tool_version: str = ""
    template_version: str = ""
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "change_id": self.change_id,
            "base_hash": self.base_hash,
            "target_hash": self.target_hash or self.content_hash(),
            "operations": [_to_jsonable(item) for item in self.operations],
            "created_at": self.created_at,
            "author": self.author,
            "tool_version": self.tool_version,
            "template_version": self.template_version,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ChangeSet":
        data = data or {}
        return cls(
            change_id=str(data.get("change_id") or ""),
            base_hash=str(data.get("base_hash") or ""),
            target_hash=str(data.get("target_hash") or ""),
            operations=[
                ChangeOperation.from_dict(item)
                for item in data.get("operations", [])
            ],
            created_at=str(data.get("created_at") or _utc_now()),
            author=str(data.get("author") or ""),
            tool_version=str(data.get("tool_version") or ""),
            template_version=str(data.get("template_version") or ""),
            notes=list(data.get("notes") or []),
        )

    def content_hash(self) -> str:
        payload = {
            "change_id": self.change_id,
            "base_hash": self.base_hash,
            "operations": self.operations,
            "author": self.author,
            "tool_version": self.tool_version,
            "template_version": self.template_version,
            "notes": self.notes,
        }
        return _canonical_hash(payload)

    def validate_base(self, current_hash: str) -> None:
        if not self.base_hash:
            raise ValueError("change set has no base_hash")
        if current_hash != self.base_hash:
            raise ValueError(
                "change set base hash does not match the current document; "
                "re-open the latest version and re-apply"
            )


@dataclass
class VersionRef:
    """A restorable document version."""

    version_id: str
    sha256: str
    parent_id: str = ""
    created_at: str = field(default_factory=_utc_now)
    author: str = ""
    message: str = ""
    tool_version: str = ""
    template_version: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version_id": self.version_id,
            "sha256": self.sha256,
            "parent_id": self.parent_id,
            "created_at": self.created_at,
            "author": self.author,
            "message": self.message,
            "tool_version": self.tool_version,
            "template_version": self.template_version,
            "metadata": _to_jsonable(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "VersionRef":
        data = data or {}
        return cls(
            version_id=str(data.get("version_id") or ""),
            sha256=str(data.get("sha256") or ""),
            parent_id=str(data.get("parent_id") or ""),
            created_at=str(data.get("created_at") or _utc_now()),
            author=str(data.get("author") or ""),
            message=str(data.get("message") or ""),
            tool_version=str(data.get("tool_version") or ""),
            template_version=str(data.get("template_version") or ""),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass
class FidelityReport:
    """What survived a render/convert/export, and what did not."""

    source_format: str
    target_format: str
    preserved: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    renderer: str = ""
    renderer_version: str = ""
    template_version: str = ""

    def status(self) -> str:
        if self.dropped or self.unsupported:
            return "lossy"
        if self.modified:
            return "partial"
        return "exact"

    def is_safe_to_export(self) -> bool:
        """An export with known losses is allowed only after explicit review."""
        return self.status() == "exact"

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_format": self.source_format,
            "target_format": self.target_format,
            "status": self.status(),
            "preserved": list(self.preserved),
            "modified": list(self.modified),
            "dropped": list(self.dropped),
            "unsupported": list(self.unsupported),
            "notes": list(self.notes),
            "renderer": self.renderer,
            "renderer_version": self.renderer_version,
            "template_version": self.template_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "FidelityReport":
        data = data or {}
        return cls(
            source_format=str(data.get("source_format") or ""),
            target_format=str(data.get("target_format") or ""),
            preserved=list(data.get("preserved") or []),
            modified=list(data.get("modified") or []),
            dropped=list(data.get("dropped") or []),
            unsupported=list(data.get("unsupported") or []),
            notes=list(data.get("notes") or []),
            renderer=str(data.get("renderer") or ""),
            renderer_version=str(data.get("renderer_version") or ""),
            template_version=str(data.get("template_version") or ""),
        )


@dataclass
class DocumentCapabilities:
    """What an adapter can and cannot do for one source format."""

    source_format: str
    supported: list[str] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def supports(self, feature: str) -> bool:
        return feature in self.supported and feature not in self.unsupported

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_format": self.source_format,
            "supported": list(self.supported),
            "unsupported": list(self.unsupported),
            "warnings": list(self.warnings),
        }

"""JSON serialization for the shared document IR.

The schema version is part of the payload.  Readers reject unknown versions
instead of guessing, so a future IR change cannot silently corrupt a project.
"""
from __future__ import annotations

import json
from typing import Any

from app.core.documents.ir import DocumentIR, SCHEMA_VERSION


def document_to_dict(document: DocumentIR) -> dict[str, Any]:
    payload = document.to_dict()
    payload["schema_version"] = SCHEMA_VERSION
    return payload


def document_from_dict(data: dict[str, Any] | None) -> DocumentIR:
    return DocumentIR.from_dict(data or {})


def dumps_document(document: DocumentIR, *, indent: int | None = 2) -> str:
    return json.dumps(
        document_to_dict(document),
        ensure_ascii=False,
        indent=indent,
        sort_keys=False,
    )


def loads_document(raw: str) -> DocumentIR:
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("document payload must be a JSON object")
    return document_from_dict(data)


def validate_document_dict(data: dict[str, Any] | None) -> list[str]:
    """Return human-readable contract errors; empty means valid."""
    errors: list[str] = []
    data = data or {}
    version = data.get("schema_version")
    if version != SCHEMA_VERSION:
        errors.append(
            f"schema_version must be {SCHEMA_VERSION!r}, got {version!r}"
        )
    if not isinstance(data.get("document_id"), str) or not data.get("document_id"):
        errors.append("document_id is required")
    if not isinstance(data.get("kind"), str) or not data.get("kind"):
        errors.append("kind is required")
    if not isinstance(data.get("blocks"), list):
        errors.append("blocks must be a list")
    for index, block in enumerate(data.get("blocks") or []):
        if not isinstance(block, dict):
            errors.append(f"blocks[{index}] must be an object")
            continue
        if not block.get("id"):
            errors.append(f"blocks[{index}].id is required")
        if not block.get("kind"):
            errors.append(f"blocks[{index}].kind is required")
    return errors

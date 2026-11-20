"""Load thesis templates contributed as JSON files.

Canonical location is ``thesis-templates/`` at the repository root.  A packaged
(desktop) build ships the same directory next to the bundled backend.  Invalid
templates are skipped with a warning instead of taking the whole app down.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger()

REQUIRED_KEYS = (
    "id", "name", "description", "source", "version",
    "degree", "page", "margins", "headings",
)
_CACHE: list[dict[str, Any]] | None = None

# Must match thesis-templates/schema.json; kept here so the runtime does not
# depend on jsonschema (the validator script does the full check in CI).
_ID_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789-")


def templates_dir() -> Path | None:
    """First directory that looks like a template library."""
    candidates: list[Path] = []
    override = os.environ.get("NOVA_THESIS_TEMPLATES")
    if override:
        candidates.append(Path(override))
    candidates.append(Path(__file__).resolve().parents[4] / "thesis-templates")
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        candidates.append(base / "thesis-templates")
        candidates.append(Path(sys.executable).parent / "thesis-templates")
    candidates.append(Path.cwd() / "thesis-templates")
    for candidate in candidates:
        if (candidate / "schema.json").is_file():
            return candidate
    return None


def _valid(template: dict[str, Any]) -> tuple[bool, str]:
    for key in REQUIRED_KEYS:
        if key not in template:
            return False, f"缺少字段 {key}"
    template_id = str(template["id"])
    if len(template_id) < 3 or len(template_id) > 80:
        return False, "id 长度不合法"
    if not set(template_id) <= _ID_CHARS or not template_id[0].isalnum():
        return False, "id 只能包含小写字母、数字和连字符"
    if template["degree"] not in ("undergraduate", "master", "doctor"):
        return False, "degree 必须是 undergraduate/master/doctor"
    try:
        page = template["page"]
        margins = template["margins"]
        headings = template["headings"]
        for key in ("width_cm", "height_cm", "tolerance_cm"):
            float(page[key])
        for key in ("top_cm", "bottom_cm", "left_cm", "right_cm", "tolerance_cm"):
            float(margins[key])
        max_level = int(headings["max_level"])
        if not 1 <= max_level <= 6:
            return False, "headings.max_level 必须在 1–6 之间"
        bool(headings["allow_skip"])
    except (KeyError, TypeError, ValueError) as exc:
        return False, f"页面/边距/标题字段不合法：{exc}"
    return True, ""


def load_templates(force: bool = False) -> list[dict[str, Any]]:
    """Read every ``*/template.json`` under the template library.

    Returns an empty list when the directory is missing; callers fall back to
    the built-in sample template.
    """
    global _CACHE
    if _CACHE is not None and not force:
        return _CACHE
    directory = templates_dir()
    templates: list[dict[str, Any]] = []
    seen: set[str] = set()
    if directory is None:
        _CACHE = templates
        return templates
    for path in sorted(directory.glob("*/template.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("thesis_template_unreadable", path=str(path), error=str(exc))
            continue
        if not isinstance(payload, dict):
            logger.warning("thesis_template_invalid", path=str(path), error="not an object")
            continue
        ok, reason = _valid(payload)
        if not ok:
            logger.warning("thesis_template_invalid", path=str(path), error=reason)
            continue
        if payload["id"] in seen:
            logger.warning("thesis_template_duplicate", path=str(path), id=payload["id"])
            continue
        payload.setdefault("is_sample", True)
        seen.add(payload["id"])
        templates.append(payload)
    _CACHE = templates
    return templates


def reload_templates() -> list[dict[str, Any]]:
    return load_templates(force=True)

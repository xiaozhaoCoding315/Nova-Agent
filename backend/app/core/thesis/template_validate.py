"""Full JSON-Schema validation for contributed thesis templates.

The runtime loader only enforces the fields it needs; this validator is the CI
gate: schema errors, duplicate ids, and missing SOURCE.md are all fatal.
"""
from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from app.core.thesis.template_store import templates_dir


def _default_root() -> Path:
    found = templates_dir()
    if found is None:
        return Path(__file__).resolve().parents[4] / "thesis-templates"
    return found


def validate_templates(root: Path | None = None) -> list[str]:
    root = root or _default_root()
    schema_path = root / "schema.json"
    if not schema_path.is_file():
        return [f"{schema_path}: 缺少 schema.json"]
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        validator = Draft202012Validator(schema)
    except (OSError, json.JSONDecodeError) as exc:
        return [f"{schema_path}: 无法读取 schema：{exc}"]
    errors: list[str] = []
    seen: dict[str, Path] = {}
    for path in sorted(root.glob("*/template.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{path}: 无法读取 JSON：{exc}")
            continue
        for error in sorted(validator.iter_errors(payload), key=lambda item: list(item.path)):
            where = "/".join(str(part) for part in error.path) or "(root)"
            errors.append(f"{path}: {where}: {error.message}")
        template_id = payload.get("id") if isinstance(payload, dict) else None
        if isinstance(template_id, str):
            if template_id in seen:
                errors.append(f"{path}: id 与 {seen[template_id]} 重复：{template_id}")
            else:
                seen[template_id] = path
        if not (path.parent / "SOURCE.md").is_file():
            errors.append(f"{path}: 缺少 SOURCE.md（模板必须记录来源与适用范围）")
    if not seen:
        errors.append(f"{root}: 没有找到任何模板")
    return errors

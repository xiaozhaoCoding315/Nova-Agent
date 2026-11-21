"""Template schema and loader tests (no database required)."""
from __future__ import annotations

import json
from pathlib import Path

from app.core.thesis.template_store import load_templates
from app.core.thesis.template_validate import validate_templates

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / "thesis-templates"


def test_contributed_templates_validate() -> None:
    assert validate_templates() == []


def test_at_least_three_sample_templates_load() -> None:
    templates = load_templates(force=True)
    assert len(templates) >= 3
    ids = [template["id"] for template in templates]
    assert len(ids) == len(set(ids))
    for template in templates:
        assert template["source"]
        assert template["version"]
        assert template["is_sample"] is True


def test_schema_rejects_template_without_source(tmp_path: Path) -> None:
    schema = json.loads((TEMPLATES / "schema.json").read_text(encoding="utf-8"))
    (tmp_path / "schema.json").write_text(
        json.dumps(schema, ensure_ascii=False), encoding="utf-8"
    )
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "template.json").write_text(
        json.dumps({
            "id": "broken-template",
            "name": "坏模板",
            "description": "缺少 source",
            "version": "2026.1",
            "degree": "undergraduate",
            "page": {"size": "A4", "width_cm": 21, "height_cm": 29.7, "tolerance_cm": 0.1},
            "margins": {
                "top_cm": 2.5, "bottom_cm": 2.5, "left_cm": 3.0,
                "right_cm": 2.5, "tolerance_cm": 0.2,
            },
            "headings": {"max_level": 3, "allow_skip": False},
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    (broken / "SOURCE.md").write_text("测试模板", encoding="utf-8")
    errors = validate_templates(tmp_path)
    assert any("source" in error for error in errors)

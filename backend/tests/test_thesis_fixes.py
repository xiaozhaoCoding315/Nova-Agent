"""Patcher tests: preview, apply and headroom checks (no database required)."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from app.core.thesis.docx.parser import parse_docx
from app.core.thesis.docx.patcher import FixError, apply_fix_file, preview_fix
from app.core.thesis.rules.builtin import GENERIC_TEMPLATE
from app.core.thesis.rules.engine import run_rules

SAMPLES = Path(__file__).resolve().parents[2] / "thesis-samples"


def _issue(model, rule_id: str):
    return next(issue for issue in run_rules(model, GENERIC_TEMPLATE["id"]) if issue.rule_id == rule_id)


def test_page_size_and_margin_fixes_apply() -> None:
    source = SAMPLES / "format-problem.docx"
    model = parse_docx(source)
    for rule_id in ("format.page_size", "format.margins"):
        issue = _issue(model, rule_id)
        assert issue.fix_type in ("set_page_size", "set_margins")
        preview = preview_fix(source, issue.fix_type, issue.fix_payload)
        assert preview["verification"]["ok"] is True
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "patched.docx"
            apply_fix_file(source, destination, issue.fix_type, issue.fix_payload)
            patched = parse_docx(destination)
            if rule_id == "format.page_size":
                assert patched.sections[0].page_width_cm == pytest.approx(21.0, abs=0.01)
                assert patched.sections[0].page_height_cm == pytest.approx(29.7, abs=0.01)
            else:
                section = patched.sections[0]
                assert section.top_margin_cm == pytest.approx(2.5, abs=0.01)
                assert section.left_margin_cm == pytest.approx(3.0, abs=0.01)
            assert patched.stats["paragraph_count"] == model.stats["paragraph_count"]
            assert patched.stats["char_count"] == model.stats["char_count"]


def test_heading_style_fix_applies() -> None:
    source = SAMPLES / "structure-problem.docx"
    model = parse_docx(source)
    issue = _issue(model, "structure.heading_style")
    assert issue.fix_type == "set_heading_style"
    with tempfile.TemporaryDirectory() as tmp:
        destination = Path(tmp) / "patched.docx"
        result = apply_fix_file(source, destination, issue.fix_type, issue.fix_payload)
        block_index = int(issue.fix_payload["block_index"])
        block = next(item for item in result["model"].blocks if item.index == block_index)
        assert block.style.startswith("Heading")
        assert block.heading_level == issue.fix_payload["level"]


def test_heading_fix_refuses_changed_paragraph() -> None:
    source = SAMPLES / "structure-problem.docx"
    issue = _issue(parse_docx(source), "structure.heading_style")
    payload = dict(issue.fix_payload)
    payload["expected_text"] = "这段文字已经不存在"
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(FixError):
            apply_fix_file(source, Path(tmp) / "patched.docx", issue.fix_type, payload)


def test_unsupported_fix_is_rejected() -> None:
    with pytest.raises(FixError):
        preview_fix(SAMPLES / "clean-sample.docx", "delete_paragraph", {})

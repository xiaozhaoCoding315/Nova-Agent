"""DOCX parsing and M0 rule tests for thesis mode (no database required)."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.core.thesis.docx.parser import parse_docx
from app.core.thesis.models import Block, DocumentModel, SectionInfo
from app.core.thesis.rules.builtin import GENERIC_TEMPLATE
from app.core.thesis.rules.engine import run_rules

SAMPLES = Path(__file__).resolve().parents[2] / "thesis-samples"


@pytest.fixture(scope="module")
def clean_model() -> DocumentModel:
    return parse_docx(SAMPLES / "clean-sample.docx")


def test_samples_exist() -> None:
    for name in (
        "clean-sample.docx",
        "format-problem.docx",
        "structure-problem.docx",
        "citation-problem.docx",
    ):
        assert (SAMPLES / name).is_file(), f"missing sample: {name}"


def test_clean_sample_parses_without_losing_content(clean_model: DocumentModel) -> None:
    assert clean_model.stats["paragraph_count"] > 0
    assert clean_model.stats["table_count"] == 1
    assert clean_model.stats["heading_count"] >= 10
    assert clean_model.sections[0].page_width_cm == pytest.approx(21.0, abs=0.01)
    assert clean_model.sections[0].page_height_cm == pytest.approx(29.7, abs=0.01)
    assert clean_model.sections[0].left_margin_cm == pytest.approx(3.0, abs=0.01)
    assert clean_model.sections[0].has_page_number is True

    text = "\n".join(block.text for block in clean_model.blocks)
    assert "学生在提交论文前通常需要反复检查" in text
    assert "表 1 系统模块说明" in text
    table = next(block for block in clean_model.blocks if block.kind == "table")
    assert table.rows == 3
    assert table.cols == 3
    assert "解析器" in table.text

    levels = [item["level"] for item in clean_model.outline]
    assert levels[0] == 1
    assert 3 in levels


def test_clean_sample_has_no_rule_issues(clean_model: DocumentModel) -> None:
    assert run_rules(clean_model, GENERIC_TEMPLATE["id"]) == []


def test_format_problem_flags_page_size_and_margins() -> None:
    model = parse_docx(SAMPLES / "format-problem.docx")
    issues = run_rules(model, GENERIC_TEMPLATE["id"])
    rule_ids = {issue.rule_id for issue in issues}
    assert "format.page_size" in rule_ids
    assert "format.margins" in rule_ids
    assert not any(issue.rule_id.startswith("structure.") for issue in issues)


def test_structure_problem_flags_heading_hierarchy_and_style() -> None:
    model = parse_docx(SAMPLES / "structure-problem.docx")
    issues = run_rules(model, GENERIC_TEMPLATE["id"])
    rule_ids = {issue.rule_id for issue in issues}
    assert "structure.heading_hierarchy" in rule_ids
    assert "structure.heading_style" in rule_ids
    assert not any(issue.rule_id.startswith("format.") for issue in issues)


def test_parse_does_not_modify_source_or_hash(clean_model: DocumentModel) -> None:
    path = SAMPLES / "clean-sample.docx"
    before = path.read_bytes()
    model = parse_docx(path)
    after = path.read_bytes()
    assert before == after
    assert model.sha256 == clean_model.sha256
    assert len(model.sha256) == 64


def test_document_model_round_trip(clean_model: DocumentModel) -> None:
    restored = DocumentModel.from_dict(clean_model.to_dict())
    assert restored.filename == clean_model.filename
    assert restored.sha256 == clean_model.sha256
    assert restored.outline == clean_model.outline
    assert len(restored.blocks) == len(clean_model.blocks)
    assert restored.sections[0].left_margin_cm == clean_model.sections[0].left_margin_cm


def test_heading_hierarchy_edge_cases() -> None:
    model = DocumentModel(
        filename="synthetic.docx",
        sha256="0" * 64,
        size=0,
        sections=[SectionInfo(index=0, page_width_cm=21.0, page_height_cm=29.7,
                              top_margin_cm=2.5, bottom_margin_cm=2.5,
                              left_margin_cm=3.0, right_margin_cm=2.5)],
        blocks=[
            Block(index=0, kind="paragraph", style="Heading 2", text="从二级开始",
                  heading_level=2),
            Block(index=1, kind="paragraph", style="Heading 4", text="跳到四级",
                  heading_level=4),
            Block(index=2, kind="paragraph", style="Heading 2", text="", heading_level=2),
        ],
        outline=[
            {"level": 2, "text": "从二级开始", "block_index": 0, "style": "Heading 2"},
            {"level": 4, "text": "跳到四级", "block_index": 1, "style": "Heading 4"},
            {"level": 2, "text": "", "block_index": 2, "style": "Heading 2"},
        ],
    )
    issues = run_rules(model, GENERIC_TEMPLATE["id"])
    titles = {issue.title for issue in issues}
    assert "首个标题不是一级标题" in titles
    assert "标题层级超出模板范围" in titles
    assert "标题层级跳跃" in titles
    assert "标题内容为空" in titles

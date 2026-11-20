"""L1 citation extraction and cross-check tests (no database required)."""
from __future__ import annotations

from pathlib import Path

from app.core.thesis.citations.extract import audit_citations
from app.core.thesis.docx.parser import parse_docx
from app.core.thesis.models import Block, DocumentModel, SectionInfo
from app.core.thesis.rules.builtin import GENERIC_TEMPLATE, get_template
from app.core.thesis.rules.engine import run_rules

SAMPLES = Path(__file__).resolve().parents[2] / "thesis-samples"
HUMANITIES = "nova-demo-humanities-2026"


def test_clean_sample_has_no_citation_issues() -> None:
    model = parse_docx(SAMPLES / "clean-sample.docx")
    audit = audit_citations(model, get_template(HUMANITIES))
    assert len(audit["references"]) == 5
    assert len(audit["in_text"]) == 5
    assert audit["issues"] == []
    assert all(item["status"] == "matched" for item in audit["in_text"])


def test_citation_problem_flags_expected_rules() -> None:
    model = parse_docx(SAMPLES / "citation-problem.docx")
    audit = audit_citations(model, get_template(HUMANITIES))
    rule_ids = {issue.rule_id for issue in audit["issues"]}
    assert "citation.reference_missing" in rule_ids
    assert "citation.reference_duplicate" in rule_ids
    assert "citation.reference_numbering" in rule_ids
    assert "citation.order" in rule_ids
    assert len(audit["references"]) == 4


def test_generic_template_disables_citation_checks() -> None:
    model = parse_docx(SAMPLES / "citation-problem.docx")
    audit = audit_citations(model, GENERIC_TEMPLATE)
    assert audit["issues"] == []
    assert run_rules(model, GENERIC_TEMPLATE["id"]) == [] or not any(
        issue.rule_id.startswith("citation.") for issue in run_rules(model, GENERIC_TEMPLATE["id"])
    )


def test_author_year_citations_are_matched() -> None:
    model = DocumentModel(
        filename="author-year.docx",
        sha256="0" * 64,
        size=0,
        sections=[SectionInfo(index=0, page_width_cm=21.0, page_height_cm=29.7)],
        blocks=[
            Block(index=0, kind="paragraph", style="Heading 1", text="1 绪论", heading_level=1),
            Block(index=1, kind="paragraph", style="正文", text="已有研究指出这一点（张三，2020）。"),
            Block(index=2, kind="paragraph", style="Heading 1", text="参考文献", heading_level=1),
            Block(index=3, kind="paragraph", style="正文", text="[1] 张三. 示例研究[J]. 示例期刊, 2020."),
        ],
        outline=[
            {"level": 1, "text": "1 绪论", "block_index": 0, "style": "Heading 1"},
        ],
    )
    template = {
        "id": "author-year-test",
        "name": "test",
        "description": "test",
        "source": "test",
        "version": "2026.1",
        "degree": "undergraduate",
        "page": {"size": "A4", "width_cm": 21, "height_cm": 29.7, "tolerance_cm": 0.1},
        "margins": {
            "top_cm": 2.5, "bottom_cm": 2.5, "left_cm": 3.0,
            "right_cm": 2.5, "tolerance_cm": 0.2,
        },
        "headings": {"max_level": 3, "allow_skip": False},
        "references": {"enabled": True, "min_entries": 0, "numbering_required": True},
    }
    audit = audit_citations(model, template)
    author_year = [item for item in audit["in_text"] if item["kind"] == "author_year"]
    assert len(author_year) == 1
    assert author_year[0]["status"] == "matched"
    assert audit["references"][0]["cited"] is False  # author-year does not set numeric "cited"

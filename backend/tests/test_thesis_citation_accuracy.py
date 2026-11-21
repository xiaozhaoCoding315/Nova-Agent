"""Synthetic 100-annotation regression set for citation L1.

This is not a field-accuracy study; it pins the deterministic extraction and
matching behaviour so regressions are caught.  The acceptance target in the
roadmap is ≥90% on 100 annotations.
"""
from __future__ import annotations

from app.core.thesis.citations.extract import audit_citations
from app.core.thesis.models import Block, DocumentModel

TEMPLATE = {
    "references": {
        "enabled": True,
        "min_entries": 0,
        "numbering_required": True,
        "section_patterns": ["参考文献", "References"],
    }
}


def _document() -> DocumentModel:
    blocks: list[Block] = [
        Block(index=0, text="1 绪论", heading_level=1),
    ]
    # 50 numeric citations [1]..[50], first-appearance order ascending.
    for number in range(1, 51):
        blocks.append(
            Block(
                index=len(blocks),
                text=f"第 {number} 项研究使用了该方法的扩展形式[{number}]，并给出实验对比。",
            )
        )
    # 50 author-year citations（作者A51，2020）…（作者A100，2024）.
    for number in range(51, 101):
        year = 2020 + (number - 51) % 5
        blocks.append(
            Block(
                index=len(blocks),
                text=f"相关工作（作者A{number}，{year}）讨论了同一问题。",
            )
        )

    blocks.append(Block(index=len(blocks), text="参考文献", heading_level=1))
    for number in range(1, 101):
        year = 2024 if number <= 50 else 2020 + (number - 51) % 5
        blocks.append(
            Block(
                index=len(blocks),
                text=(
                    f"[{number}] 作者A{number}. 题名{number}[J]. 示例期刊, "
                    f"{year}, 1(1): 1-10."
                ),
            )
        )
    return DocumentModel(
        filename="synthetic-100.docx",
        sha256="0" * 64,
        size=1,
        blocks=blocks,
    )


def test_hundred_annotations_are_extracted_and_matched():
    audit = audit_citations(_document(), TEMPLATE)
    assert len(audit["references"]) == 100
    assert len(audit["in_text"]) == 100
    assert all(item["status"] == "matched" for item in audit["in_text"])
    assert not [
        issue for issue in audit["issues"] if issue.rule_id == "citation.reference_missing"
    ]

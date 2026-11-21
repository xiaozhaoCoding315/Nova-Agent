"""Contract tests for the shared document IR (M1)."""
from __future__ import annotations

import json

import pytest

from app.core.documents import (
    ChangeOperation,
    ChangeSet,
    DocumentCapabilities,
    DocumentIR,
    FidelityReport,
    SCHEMA_VERSION,
    document_from_dict,
    document_to_dict,
    parse_markdown,
)


SAMPLE = """# 项目报告

这是第一段，包含 **加粗**、*斜体*、`代码` 和 [链接](https://example.com)。

## 结果

- 第一项
- 第二项

| 指标 | 数值 |
| --- | --- |
| 通过 | 3 |
| 失败 | 1 |

```python
print("hello")
```

> 引用一段说明。

![架构图](assets/arch.png)
"""


def test_parse_markdown_builds_expected_blocks() -> None:
    doc = parse_markdown(
        SAMPLE,
        document_id="report-1",
        kind="report",
        path="manuscripts/report.md",
        title="项目报告",
    )

    assert doc.document_id == "report-1"
    assert doc.kind == "report"
    assert doc.title == "项目报告"
    assert [block.kind for block in doc.blocks] == [
        "heading",
        "paragraph",
        "heading",
        "list",
        "table",
        "code",
        "quote",
        "image",
    ]
    assert doc.blocks[0].level == 1
    assert doc.blocks[2].level == 2
    assert doc.blocks[3].attrs["ordered"] is False
    assert len(doc.blocks[3].items) == 2
    assert doc.blocks[4].rows[1][0][0].text == "通过"
    assert doc.blocks[5].attrs["language"] == "python"
    assert "hello" in doc.blocks[5].text
    assert doc.blocks[7].kind == "image"
    assert doc.blocks[7].attrs["target"] == "assets/arch.png"
    assert doc.blocks[7].text == "架构图"


def test_inline_markup_is_structured() -> None:
    doc = parse_markdown("这是 **加粗** 和 *斜体* 以及 `代码` 和 [链接](https://example.com)。")
    kinds = [inline.kind for inline in doc.blocks[0].inlines]
    assert "strong" in kinds
    assert "emphasis" in kinds
    assert "code" in kinds
    assert "link" in kinds
    assert "加粗" in doc.blocks[0].plain_text()
    assert "斜体" in doc.blocks[0].plain_text()
    assert "代码" in doc.blocks[0].plain_text()


def test_roundtrip_json_preserves_blocks_and_hash() -> None:
    doc = parse_markdown(SAMPLE, document_id="report-1", path="report.md")
    payload = document_to_dict(doc)
    assert payload["schema_version"] == SCHEMA_VERSION

    restored = document_from_dict(json.loads(json.dumps(payload, ensure_ascii=False)))
    assert restored.content_hash() == doc.content_hash()
    assert [block.kind for block in restored.blocks] == [
        block.kind for block in doc.blocks
    ]
    assert restored.blocks[4].rows == doc.blocks[4].rows


def test_unknown_schema_version_is_rejected() -> None:
    payload = document_to_dict(parse_markdown("# hi", document_id="d1"))
    payload["schema_version"] = "doc-ir-999"
    with pytest.raises(ValueError, match="unsupported document schema_version"):
        document_from_dict(payload)


def test_unsupported_constructs_are_visible_and_preserved() -> None:
    source = """<div>raw html</div>

[^1]: a footnote

$$
x = 1
$$
"""
    doc = parse_markdown(source, document_id="d2")
    codes = {item.code for item in doc.diagnostics}
    assert {"html_block", "footnote", "math_block"} <= codes
    assert all(item.severity == "unsupported" for item in doc.unsupported_diagnostics())
    text = doc.plain_text()
    assert "raw html" in text
    assert "a footnote" in text
    assert "x = 1" in text


def test_changeset_requires_matching_base_hash() -> None:
    doc = parse_markdown("# 标题", document_id="d3")
    current = doc.content_hash()
    changes = ChangeSet(
        change_id="c1",
        base_hash=current,
        operations=[
            ChangeOperation(
                op="update",
                target_id="b1",
                before_hash=doc.blocks[0].source.content_hash
                if doc.blocks[0].source
                else "",
                payload={"text": "新标题"},
            )
        ],
        author="u1",
    )

    changes.validate_base(current)
    with pytest.raises(ValueError, match="does not match"):
        changes.validate_base("sha256:not-the-current-document")

    first = changes.content_hash()
    changes.operations.append(
        ChangeOperation(op="delete", target_id="b1")
    )
    assert changes.content_hash() != first


def test_fidelity_report_is_honest_about_loss() -> None:
    exact = FidelityReport(source_format="markdown", target_format="docx")
    assert exact.status() == "exact"
    assert exact.is_safe_to_export()

    partial = FidelityReport(
        source_format="docx",
        target_format="pdf",
        modified=["page numbers"],
    )
    assert partial.status() == "partial"
    assert not partial.is_safe_to_export()

    lossy = FidelityReport(
        source_format="docx",
        target_format="markdown",
        dropped=["text boxes"],
        unsupported=["tracked changes"],
    )
    assert lossy.status() == "lossy"
    assert not lossy.is_safe_to_export()
    assert lossy.to_dict()["status"] == "lossy"


def test_capabilities_distinguish_supported_from_unsupported() -> None:
    caps = DocumentCapabilities(
        source_format="docx",
        supported=["paragraphs", "tables"],
        unsupported=["tracked changes", "text boxes"],
        warnings=["fonts may differ in Word/WPS"],
    )
    assert caps.supports("paragraphs")
    assert not caps.supports("tracked changes")
    assert not caps.supports("unknown")


def test_document_ir_can_be_built_directly() -> None:
    doc = DocumentIR(document_id="manual", kind="resume", title="简历")
    assert doc.schema_version == SCHEMA_VERSION
    assert doc.content_hash().startswith("sha256:")
    assert document_to_dict(doc)["schema_version"] == SCHEMA_VERSION

"""Report/export builders (no database required)."""
from __future__ import annotations

import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from app.core.thesis.citations.extract import audit_citations
from app.core.thesis.docx.parser import parse_docx
from app.core.thesis.report.builder import (
    build_disclosure_docx,
    build_report_docx,
    citations_csv,
    render_report_html,
    write_export_package,
    write_stage_package,
)
from app.core.thesis.rules.builtin import get_template
from app.core.thesis.rules.engine import run_rules

SAMPLES = Path(__file__).resolve().parents[2] / "thesis-samples"
TEMPLATE_ID = "nova-demo-humanities-2026"


def _fixture():
    model = parse_docx(SAMPLES / "citation-problem.docx")
    template = get_template(TEMPLATE_ID)
    audit = audit_citations(model, template)
    drafts = run_rules(model, template["id"], citation_audit=audit)
    issues = [
        {
            "id": str(index),
            "severity": draft.severity,
            "rule_id": draft.rule_id,
            "title": draft.title,
            "detail": draft.detail,
            "location": draft.location,
            "status": "open",
            "source": draft.source,
            "confidence": draft.confidence,
        }
        for index, draft in enumerate(drafts)
    ]
    project = {
        "id": "p1",
        "title": "示例论文",
        "school": "示例大学",
        "degree": "undergraduate",
        "template_id": template["id"],
    }
    public_template = {
        "id": template["id"],
        "name": template["name"],
        "description": template["description"],
        "source": template["source"],
        "version": template["version"],
        "degree": template["degree"],
        "is_sample": True,
    }
    document = {"filename": model.filename, "sha256": model.sha256}
    report = {
        "project": project,
        "document": document,
        "template": public_template,
        "counts": {
            "blocker": sum(1 for issue in issues if issue["severity"] == "blocker"),
            "warn": sum(1 for issue in issues if issue["severity"] == "warn"),
            "info": sum(1 for issue in issues if issue["severity"] == "info"),
            "total": len(issues),
        },
        "issues": issues,
        "generated_at": datetime.now(timezone.utc),
    }
    return report, audit, template, project


def test_report_html_contains_evidence_and_limitations() -> None:
    report, audit, _, _ = _fixture()
    html_text = render_report_html(report, audit, [], [])
    assert "论文体检报告" in html_text
    assert "示例论文" in html_text
    assert "citation.reference_missing" in html_text
    assert "局限与人工确认" in html_text
    assert "不等同于学校的最终格式审查" in html_text


def test_report_docx_and_disclosure_docx_are_valid_zip_packages() -> None:
    report, audit, template, project = _fixture()
    report_bytes = build_report_docx(report, audit, [], [])
    disclosure_bytes = build_disclosure_docx(project, template, [])
    assert report_bytes[:2] == b"PK"
    assert disclosure_bytes[:2] == b"PK"
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "report.docx"
        path.write_bytes(report_bytes)
        parsed = parse_docx(path)
        assert parsed.stats["paragraph_count"] > 0


def test_citations_csv_has_bom_and_rows() -> None:
    _, audit, _, _ = _fixture()
    content = citations_csv(audit)
    assert content.startswith("﻿")
    assert "类型,编号,原文,状态,位置,说明,DOI/元数据（L2）,全文证据（L3）" in content
    assert "参考文献" in content
    assert "文内引用" in content


def test_citations_csv_includes_l2_and_l3_columns() -> None:
    audit = {
        "references": [
            {
                "index": 1,
                "raw": "[1] 示例作者. 示例文献[J]. 示例期刊, 2022.",
                "cited": True,
                "metadata_status": "verified",
                "metadata": {"detail": "DOI、题名与年份一致"},
                "evidence_page": 3,
                "evidence_support": "supported",
                "evidence_quote": "候选原文片段",
            }
        ],
        "in_text": [],
    }
    content = citations_csv(audit)
    assert "已核实：DOI、题名与年份一致" in content
    assert "第 3 页 · 支持" in content
    assert "候选原文片段" in content


def test_export_package_contains_expected_files_and_stays_safe() -> None:
    report, audit, template, project = _fixture()
    with tempfile.TemporaryDirectory() as tmp:
        export_dir = Path(tmp) / "exports"
        zip_path = write_export_package(
            export_dir,
            "../../逃逸/论文",
            fixed_docx=SAMPLES / "clean-sample.docx",
            report_html=render_report_html(report, audit, [], []),
            report_docx=build_report_docx(report, audit, [], []),
            disclosure_docx=build_disclosure_docx(project, template, []),
            citations_csv_text=citations_csv(audit),
            fixes=[],
            project=project,
            template=template,
            document=report["document"],
        )
        assert zip_path.parent == export_dir
        assert zip_path.name.startswith("论文")
        with zipfile.ZipFile(zip_path) as archive:
            names = set(archive.namelist())
        assert "论文体检报告.html" in names
        assert "论文体检报告.docx" in names
        assert "AI使用声明.docx" in names
        assert "引用核验清单.csv" in names
        assert "修改记录.json" in names
        assert "提交说明.md" in names
        assert any(name.endswith("_修复版.docx") for name in names)


def test_stage_packages_created_in_the_same_second_do_not_collide(tmp_path: Path) -> None:
    kwargs = {
        "stage_docx": None,
        "stage_markdown": "# 测试论文\n",
        "disclosure_docx": b"docx",
        "stage_summary": [],
        "warnings": [],
        "project": {"title": "测试论文"},
    }
    first = write_stage_package(tmp_path, "测试论文", **kwargs)
    second = write_stage_package(tmp_path, "测试论文", **kwargs)
    assert first != second
    assert first.is_file() and second.is_file()

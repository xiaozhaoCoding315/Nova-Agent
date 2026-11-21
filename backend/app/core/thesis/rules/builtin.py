"""Built-in thesis rules and template loading.

Only checks with a clear, deterministic basis live here.  Templates are JSON
files under ``thesis-templates/``; the generic fallback is a *sample* used when
no template library is available.  It does not claim to be an official standard
of any school.
"""
from __future__ import annotations

import re
from typing import Any

from app.core.thesis.citations.extract import audit_citations
from app.core.thesis.models import DocumentModel, SectionInfo
from app.core.thesis.rules.engine import IssueDraft, RuleContext
from app.core.thesis.template_store import load_templates

NUMBERED_HEADING_RE = re.compile(r"^\d+(?:\.\d+)+\s+\S")

GENERIC_TEMPLATE: dict[str, Any] = {
    "id": "generic-undergraduate-v1",
    "name": "通用本科论文模板（示例）",
    "description": "Nova 自带的演示模板，不对应任何具体学校。正式使用请导入学校的格式要求。",
    "source": "Nova 示例模板，非官方标准",
    "version": "2026.1",
    "degree": "undergraduate",
    "is_sample": True,
    "page": {
        "size": "A4",
        "width_cm": 21.0,
        "height_cm": 29.7,
        "tolerance_cm": 0.15,
    },
    "margins": {
        "top_cm": 2.5,
        "bottom_cm": 2.5,
        "left_cm": 3.0,
        "right_cm": 2.5,
        "tolerance_cm": 0.2,
    },
    "headings": {
        "max_level": 3,
        "allow_skip": False,
    },
    "page_number": {"required": False, "position": "any"},
    "required_sections": [],
    # M0 tests and the generic fallback stay citation-free until a template
    # explicitly opts in.
    "references": {"enabled": False},
}


def _all_templates() -> list[dict[str, Any]]:
    templates = load_templates()
    return templates or [GENERIC_TEMPLATE]


def get_template(template_id: str | None = None) -> dict[str, Any]:
    templates = _all_templates()
    for template in templates:
        if template["id"] == template_id:
            return template
    if template_id is None:
        return templates[0]
    for template in templates:
        if template["id"] == GENERIC_TEMPLATE["id"]:
            return template
    return GENERIC_TEMPLATE


def get_template_strict(template_id: str | None) -> dict[str, Any]:
    """User-supplied template ids must match exactly.

    ``get_template`` keeps a generic fallback for old rows and internal reads;
    silently falling back for a *new* user input would switch the school
    template and delete the previous scan results.  API inputs use this
    function instead.
    """
    if template_id is None:
        return get_template(None)
    # The built-in fallback is not in the template library on disk, but it is
    # the default for projects created without an explicit template.
    if template_id == GENERIC_TEMPLATE["id"]:
        return GENERIC_TEMPLATE
    for template in _all_templates():
        if template["id"] == template_id:
            return template
    raise ValueError(f"未知论文模板：{template_id}")


def list_templates() -> list[dict[str, Any]]:
    return [
        {
            "id": template["id"],
            "name": template["name"],
            "description": template["description"],
            "source": template["source"],
            "version": template.get("version", ""),
            "degree": template["degree"],
            "is_sample": bool(template.get("is_sample", True)),
        }
        for template in _all_templates()
    ]


def _section_label(section: SectionInfo) -> str:
    return f"第 {section.index + 1} 节"


def _page_size_issue(section: SectionInfo, page: dict[str, Any]) -> IssueDraft | None:
    tolerance = float(page["tolerance_cm"])
    expected_width = float(page["width_cm"])
    expected_height = float(page["height_cm"])
    width = section.page_width_cm
    height = section.page_height_cm
    if section.orientation.upper() == "LANDSCAPE":
        width, height = height, width
    if abs(width - expected_width) <= tolerance and abs(height - expected_height) <= tolerance:
        return None
    return IssueDraft(
        rule_id="format.page_size",
        category="format",
        severity="blocker",
        title=f"{_section_label(section)}页面尺寸不是 {page['size']}",
        detail=(
            f"当前 {width:.2f}×{height:.2f} cm，模板要求 "
            f"{expected_width:.1f}×{expected_height:.1f} cm（容差 {tolerance:.2f} cm）。"
        ),
        location={"section_index": section.index, "section": _section_label(section)},
        evidence={
            "actual": {"width_cm": width, "height_cm": height},
            "expected": {
                "width_cm": expected_width,
                "height_cm": expected_height,
                "size": page["size"],
            },
            "tolerance_cm": tolerance,
        },
        fix_type="set_page_size",
        fix_payload={
            "section_index": section.index,
            "width_cm": expected_width,
            "height_cm": expected_height,
        },
    )


class PageSizeRule:
    id = "format.page_size"
    category = "format"

    def evaluate(self, document: DocumentModel, context: RuleContext) -> list[IssueDraft]:
        page = context.template["page"]
        return [
            issue
            for section in document.sections
            if (issue := _page_size_issue(section, page)) is not None
        ]


MARGIN_SIDES = (
    ("top_cm", "top_margin_cm", "上"),
    ("bottom_cm", "bottom_margin_cm", "下"),
    ("left_cm", "left_margin_cm", "左"),
    ("right_cm", "right_margin_cm", "右"),
)


class MarginRule:
    id = "format.margins"
    category = "format"

    def evaluate(self, document: DocumentModel, context: RuleContext) -> list[IssueDraft]:
        margins = context.template["margins"]
        tolerance = float(margins["tolerance_cm"])
        issues: list[IssueDraft] = []
        for section in document.sections:
            deviations: list[dict[str, Any]] = []
            actual: dict[str, float] = {}
            for expected_key, actual_attr, label in MARGIN_SIDES:
                expected = float(margins[expected_key])
                value = float(getattr(section, actual_attr))
                actual[label] = value
                if abs(value - expected) > tolerance:
                    deviations.append({
                        "side": label,
                        "actual_cm": round(value, 2),
                        "expected_cm": expected,
                        "delta_cm": round(value - expected, 2),
                    })
            if not deviations:
                continue
            summary = "、".join(
                f"{item['side']}边距 {item['actual_cm']:.2f}cm（要求 {item['expected_cm']:.1f}cm）"
                for item in deviations
            )
            issues.append(IssueDraft(
                rule_id="format.margins",
                category="format",
                severity="warn",
                title=f"{_section_label(section)}页边距与模板不一致",
                detail=f"偏差：{summary}。",
                location={"section_index": section.index, "section": _section_label(section)},
                evidence={
                    "actual": actual,
                    "expected": {
                        "top_cm": float(margins["top_cm"]),
                        "bottom_cm": float(margins["bottom_cm"]),
                        "left_cm": float(margins["left_cm"]),
                        "right_cm": float(margins["right_cm"]),
                    },
                    "deviations": deviations,
                    "tolerance_cm": tolerance,
                },
                fix_type="set_margins",
                fix_payload={
                    "section_index": section.index,
                    "top_cm": float(margins["top_cm"]),
                    "bottom_cm": float(margins["bottom_cm"]),
                    "left_cm": float(margins["left_cm"]),
                    "right_cm": float(margins["right_cm"]),
                },
            ))
        return issues


class PageNumberRule:
    """Detect a missing PAGE field when the template requires page numbers."""

    id = "format.page_number"
    category = "format"

    def evaluate(self, document: DocumentModel, context: RuleContext) -> list[IssueDraft]:
        config = context.template.get("page_number") or {}
        if not config.get("required"):
            return []
        issues: list[IssueDraft] = []
        for section in document.sections:
            if section.has_page_number:
                continue
            issues.append(IssueDraft(
                rule_id=self.id,
                category="format",
                severity="warn",
                title=f"{_section_label(section)}未检测到页码",
                detail=(
                    "模板要求页脚（或页眉）显示页码，但没有找到 Word 的 PAGE 域。"
                    "静态数字不会被识别为页码。"
                ),
                location={"section_index": section.index, "section": _section_label(section)},
                evidence={
                    "header_text": section.header_text,
                    "footer_text": section.footer_text,
                    "expected_position": config.get("position", "footer"),
                    "has_page_number": False,
                },
            ))
        return issues


class HeadingHierarchyRule:
    id = "structure.heading_hierarchy"
    category = "structure"

    def evaluate(self, document: DocumentModel, context: RuleContext) -> list[IssueDraft]:
        outline = document.outline
        heading_config = context.template.get("headings", {})
        max_level = int(heading_config.get("max_level", 3))
        allow_skip = bool(heading_config.get("allow_skip", False))
        if not outline:
            return [IssueDraft(
                rule_id=self.id,
                category=self.category,
                severity="warn",
                title="未检测到标题样式",
                detail="全文没有使用 Heading / 标题样式，目录与层级检查无法进行。",
                location={},
                evidence={"outline_count": 0},
            )]

        issues: list[IssueDraft] = []
        previous: int | None = None
        for item in outline:
            level = int(item.get("level") or 0)
            text = str(item.get("text") or "").strip()
            block_index = int(item.get("block_index", -1))
            location = {
                "block_index": block_index,
                "paragraph_index": block_index,
                "text": text,
                "heading_level": level,
            }
            if not text:
                issues.append(IssueDraft(
                    rule_id=self.id,
                    category=self.category,
                    severity="warn",
                    title="标题内容为空",
                    detail=f"第 {block_index + 1} 个段落使用了 {level} 级标题样式，但没有文字。",
                    location=location,
                    evidence={"style": item.get("style", ""), "heading_level": level},
                ))
                continue
            if level > max_level:
                issues.append(IssueDraft(
                    rule_id=self.id,
                    category=self.category,
                    severity="warn",
                    title="标题层级超出模板范围",
                    detail=f"「{text}」是 {level} 级标题，模板只定义了 1–{max_level} 级。",
                    location=location,
                    evidence={"heading_level": level, "max_level": max_level},
                ))
            if previous is None and level != 1:
                issues.append(IssueDraft(
                    rule_id=self.id,
                    category=self.category,
                    severity="warn",
                    title="首个标题不是一级标题",
                    detail=f"第一个标题「{text}」是 {level} 级标题，通常应从一级标题开始。",
                    location=location,
                    evidence={"heading_level": level, "expected_level": 1},
                ))
            if previous is not None and level - previous > 1 and not allow_skip:
                issues.append(IssueDraft(
                    rule_id=self.id,
                    category=self.category,
                    severity="warn",
                    title="标题层级跳跃",
                    detail=(
                        f"「{text}」从 {previous} 级直接跳到 {level} 级；"
                        "请确认是否漏掉了一级标题。"
                    ),
                    location=location,
                    evidence={"previous_level": previous, "heading_level": level},
                ))
            previous = level
        return issues


class HeadingStyleRule:
    """Conservative heuristic for a numbered heading typed as body text."""

    id = "structure.heading_style"
    category = "structure"

    def evaluate(self, document: DocumentModel, _context: RuleContext) -> list[IssueDraft]:
        issues: list[IssueDraft] = []
        for block in document.blocks:
            if block.kind != "paragraph" or block.heading_level is not None:
                continue
            text = block.text.strip()
            if not text or len(text) > 80 or not NUMBERED_HEADING_RE.match(text):
                continue
            if text.endswith(("。", "！", "？", "；", ".", ";", "，", ",")):
                continue
            level = text.split(" ", 1)[0].count(".") + 1
            issues.append(IssueDraft(
                rule_id=self.id,
                category="structure",
                severity="info",
                title="疑似标题使用了正文样式",
                detail=(
                    f"「{text}」看起来像编号标题，但使用的是「{block.style or '正文'}」样式；"
                    "如果它确实是标题，请套用对应级别。"
                ),
                location={
                    "block_index": block.index,
                    "paragraph_index": block.index,
                    "text": text,
                },
                evidence={"style": block.style, "pattern": "numbered_heading"},
                fix_type="set_heading_style",
                fix_payload={
                    "block_index": block.index,
                    "level": level,
                    "expected_text": text,
                },
                confidence="medium",
            ))
        return issues


class RequiredSectionsRule:
    id = "structure.required_sections"
    category = "structure"

    def evaluate(self, document: DocumentModel, context: RuleContext) -> list[IssueDraft]:
        required = context.template.get("required_sections") or []
        if not required:
            return []
        headings = [
            str(item.get("text") or "").strip().lower()
            for item in document.outline
            if str(item.get("text") or "").strip()
        ]
        issues: list[IssueDraft] = []
        for section in required:
            patterns = [str(pattern).strip().lower() for pattern in section.get("patterns") or []]
            if not patterns:
                continue
            found = any(
                pattern in heading
                for heading in headings
                for pattern in patterns
            )
            if found:
                continue
            issues.append(IssueDraft(
                rule_id=self.id,
                category=self.category,
                severity="warn",
                title=f"未找到「{section.get('label') or section.get('key')}」部分",
                detail=(
                    "模板要求包含这一部分。检查依据是标题样式；如果该部分存在但未使用标题样式，"
                    "请先修正标题样式后重新检查。"
                ),
                location={},
                evidence={
                    "key": section.get("key"),
                    "patterns": patterns,
                    "headings": headings[:20],
                },
                confidence="medium",
            ))
        return issues


class CitationRule:
    """L1 citation checks; the audit itself lives in citations/extract.py."""

    id = "citation.l1"
    category = "citation"

    def evaluate(self, document: DocumentModel, context: RuleContext) -> list[IssueDraft]:
        audit = context.citation_audit
        if audit is None:
            audit = audit_citations(document, context.template)
        return list(audit.get("issues") or [])


RULES = [
    PageSizeRule(),
    MarginRule(),
    PageNumberRule(),
    HeadingHierarchyRule(),
    HeadingStyleRule(),
    RequiredSectionsRule(),
    CitationRule(),
]

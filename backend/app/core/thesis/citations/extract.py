"""Extract in-text citations and the reference list, then cross-check them.

This is the L1 layer: purely deterministic text matching.  It never decides
that a reference is *fake*; a missing or unmatched entry is reported as
"needs a human look", with the exact evidence attached.
"""
from __future__ import annotations

import re
from typing import Any

from app.core.thesis.models import Block, DocumentModel
from app.core.thesis.rules.engine import IssueDraft

DEFAULT_SECTION_PATTERNS = ("参考文献", "references", "bibliography")
CITATION_SOURCE = "GB/T 7714-2015 引用标注规则（L1 确定性对照）"

NUMERIC_RE = re.compile(r"[\[［](\d+(?:\s*[-–—~,，、]\s*\d+)*)[\]］]")
AUTHOR_YEAR_RE = re.compile(r"[（(]([^（）()]{1,60}?)[，,]\s*((?:19|20)\d{2})[a-zA-Z]?[）)]")
ENTRY_NUMBER_RE = re.compile(r"^\s*[\[［](\d+)[\]］]\s*")
YEAR_RE = re.compile(r"(?:19|20)\d{2}")
MAX_CITATION_ISSUES = 60


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _section_patterns(template: dict[str, Any] | None) -> tuple[str, ...]:
    references = (template or {}).get("references") or {}
    patterns = references.get("section_patterns") or DEFAULT_SECTION_PATTERNS
    return tuple(str(item) for item in patterns)


def _matches_heading(text: str, patterns: tuple[str, ...]) -> bool:
    norm = _normalize(text).lower()
    return any(norm == pattern.strip().lower() for pattern in patterns)


def find_reference_range(
    blocks: list[Block],
    patterns: tuple[str, ...],
) -> tuple[int, int] | None:
    """Return [start, end) positions in ``blocks`` covering the reference list."""
    heading_pos: int | None = None
    heading_level: int | None = None
    for pos, block in enumerate(blocks):
        if block.kind != "paragraph":
            continue
        if block.heading_level is not None and _matches_heading(block.text, patterns):
            heading_pos = pos
            heading_level = block.heading_level
            break
    if heading_pos is None:
        for pos, block in enumerate(blocks):
            if block.kind == "paragraph" and _matches_heading(block.text, patterns):
                heading_pos = pos
                heading_level = 1
                break
    if heading_pos is None:
        return None
    end = len(blocks)
    assert heading_level is not None
    for pos in range(heading_pos + 1, len(blocks)):
        block = blocks[pos]
        if (
            block.kind == "paragraph"
            and block.heading_level is not None
            and block.heading_level <= heading_level
        ):
            end = pos
            break
    return heading_pos + 1, end


def _year(text: str) -> str | None:
    match = YEAR_RE.search(text)
    return match.group(0) if match else None


def parse_references(blocks: list[Block], start: int, end: int) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for block in blocks[start:end]:
        if block.kind != "paragraph":
            continue
        text = _normalize(block.text)
        if not text:
            continue
        match = ENTRY_NUMBER_RE.match(text)
        if match:
            entries.append({
                "index": int(match.group(1)),
                "raw": text,
                "block_index": block.index,
                "year": _year(text),
            })
        elif entries:
            entries[-1]["raw"] = f"{entries[-1]['raw']} {text}"[:1000]
            entries[-1]["year"] = _year(entries[-1]["raw"])
        else:
            entries.append({
                "index": None,
                "raw": text,
                "block_index": block.index,
                "year": _year(text),
            })
    return entries


def _expand_numbers(raw: str) -> list[int]:
    numbers: list[int] = []
    for part in re.split(r"[,，、]", raw):
        part = part.strip()
        span = re.fullmatch(r"(\d+)\s*[-–—~]\s*(\d+)", part)
        if span:
            first, last = int(span.group(1)), int(span.group(2))
            if 0 < last - first <= 50:
                numbers.extend(range(first, last + 1))
            else:
                numbers.extend([first, last])
        elif part.isdigit():
            numbers.append(int(part))
    return list(dict.fromkeys(numbers))


def _split_authors(raw: str) -> list[str]:
    return [part.strip() for part in re.split(r"[,，、;；&]| and ", raw) if part.strip()]


def parse_in_text(
    blocks: list[Block],
    reference_range: tuple[int, int] | None,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for pos, block in enumerate(blocks):
        if block.kind != "paragraph" or not block.text:
            continue
        if reference_range and reference_range[0] - 1 <= pos < reference_range[1]:
            continue
        for match in NUMERIC_RE.finditer(block.text):
            numbers = _expand_numbers(match.group(1))
            if not numbers:
                continue
            items.append({
                "raw": match.group(0).strip(),
                "kind": "numeric",
                "numbers": numbers,
                "block_index": block.index,
                "context": block.text[:160],
            })
        for match in AUTHOR_YEAR_RE.finditer(block.text):
            items.append({
                "raw": match.group(0).strip(),
                "kind": "author_year",
                "authors": _split_authors(match.group(1)),
                "year": match.group(2),
                "block_index": block.index,
                "context": block.text[:160],
            })
    return items


def _match_author_year(item: dict[str, Any], references: list[dict[str, Any]]) -> dict[str, Any] | None:
    year = str(item.get("year") or "")
    authors = [name for name in item.get("authors") or [] if len(name) >= 2]
    if not year or not authors:
        return None
    for reference in references:
        raw = str(reference.get("raw") or "")
        if year in raw and any(name in raw for name in authors):
            return reference
    return None


def _issue(
    rule_id: str,
    severity: str,
    title: str,
    detail: str,
    location: dict[str, Any],
    evidence: dict[str, Any],
) -> IssueDraft:
    return IssueDraft(
        rule_id=rule_id,
        category="citation",
        severity=severity,  # type: ignore[arg-type]
        title=title,
        detail=detail,
        location=location,
        evidence=evidence,
        source=CITATION_SOURCE,
        confidence="medium",
    )


def audit_citations(
    document: DocumentModel,
    template: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return ``{references, in_text, issues}`` for one document."""
    references_config = (template or {}).get("references") or {}
    if references_config.get("enabled") is False:
        return {
            "references": [],
            "in_text": [],
            "issues": [],
            "reference_section_found": False,
            "disabled": True,
        }
    patterns = _section_patterns(template)
    ref_range = find_reference_range(document.blocks, patterns)
    references = parse_references(document.blocks, *ref_range) if ref_range else []
    in_text = parse_in_text(document.blocks, ref_range)

    reference_indexes = {entry["index"] for entry in references if entry["index"] is not None}
    cited: set[int] = set()
    for item in in_text:
        if item["kind"] == "numeric":
            cited.update(number for number in item["numbers"] if number in reference_indexes)
            status = (
                "matched"
                if all(number in reference_indexes for number in item["numbers"])
                else "missing_reference"
            )
        else:
            matched = _match_author_year(item, references)
            status = "matched" if matched else "unverified"
            if matched:
                item["matched_reference"] = matched["raw"][:300]
        item["status"] = status

    for entry in references:
        entry["cited"] = entry["index"] in cited if entry["index"] is not None else False

    issues: list[IssueDraft] = []

    if in_text and not ref_range:
        issues.append(_issue(
            "citation.references_missing",
            "warn",
            "有文内引用但未找到参考文献部分",
            "检测到文内引用标注，但没有找到「参考文献 / References」标题；"
            "请确认文末参考文献是否存在并使用标题样式。",
            {"block_index": in_text[0]["block_index"]},
            {"in_text_count": len(in_text)},
        ))
    elif ref_range and not in_text:
        issues.append(_issue(
            "citation.none_found",
            "info",
            "未检测到文内引用标注",
            "找到了参考文献列表，但正文中没有识别到 [1] 或（作者，年份）形式的引用标注；"
            "如果使用了其他格式，请人工确认。",
            {"paragraph_index": document.blocks[ref_range[0] - 1].index if ref_range else 0},
            {"reference_count": len(references)},
        ))

    seen_missing: set[tuple[int, int]] = set()
    for item in in_text:
        if item["kind"] != "numeric" or item["status"] != "missing_reference":
            continue
        missing = [number for number in item["numbers"] if number not in reference_indexes]
        for number in missing:
            key = (item["block_index"], number)
            if key in seen_missing:
                continue
            seen_missing.add(key)
            issues.append(_issue(
                "citation.reference_missing",
                "warn",
                f"文内引用 [{number}] 没有对应文献",
                f"正文第 {item['block_index'] + 1} 处引用了 [{number}]，"
                "但参考文献列表中没有该编号。请确认编号是否正确。",
                {
                    "block_index": item["block_index"],
                    "paragraph_index": item["block_index"],
                    "text": item["context"],
                    "raw": item["raw"],
                },
                {
                    "number": number,
                    "raw": item["raw"],
                    "reference_indexes": sorted(reference_indexes)[:50],
                },
            ))

    uncited = [
        entry["index"] for entry in references
        if entry["index"] is not None and entry["index"] not in cited
    ]
    if uncited:
        issues.append(_issue(
            "citation.reference_uncited",
            "info",
            "部分参考文献未在正文中引用",
            "以下编号在参考文献列表中出现，但正文中没有找到对应引用标注："
            + "、".join(f"[{number}]" for number in uncited[:12])
            + (" 等。" if len(uncited) > 12 else "。"),
            {"section_index": 0},
            {"numbers": uncited},
        ))

    duplicate_numbers: dict[int, int] = {}
    seen_raw: dict[str, int] = {}
    for entry in references:
        index = entry["index"]
        if index is not None:
            duplicate_numbers[index] = duplicate_numbers.get(index, 0) + 1
        raw_key = _normalize(entry["raw"]).lower()
        seen_raw[raw_key] = seen_raw.get(raw_key, 0) + 1
    repeated_numbers = sorted(number for number, count in duplicate_numbers.items() if count > 1)
    repeated_raw = [key for key, count in seen_raw.items() if count > 1 and key]
    if repeated_numbers or repeated_raw:
        issues.append(_issue(
            "citation.reference_duplicate",
            "warn",
            "参考文献存在重复",
            (
                ("重复编号：" + "、".join(f"[{number}]" for number in repeated_numbers) + "。")
                if repeated_numbers else ""
            )
            + (f"另有 {len(repeated_raw)} 条内容完全相同的条目。" if repeated_raw else ""),
            {"section_index": 0},
            {"duplicate_numbers": repeated_numbers, "duplicate_entries": repeated_raw[:5]},
        ))

    numbered = [entry["index"] for entry in references if entry["index"] is not None]
    if references and references_config.get("numbering_required", False):
        unnumbered = [entry for entry in references if entry["index"] is None]
        if unnumbered:
            issues.append(_issue(
                "references.entry_numbering",
                "warn",
                "参考文献条目缺少编号",
                f"{len(unnumbered)} 条参考文献没有以 [n] 编号开头，"
                "与模板要求的顺序编码制不一致。",
                {"section_index": 0, "block_index": unnumbered[0]["block_index"]},
                {"entries": [entry["raw"][:160] for entry in unnumbered[:8]]},
            ))
    if numbered and sorted(set(numbered)) != list(range(1, max(numbered) + 1)):
        issues.append(_issue(
            "citation.reference_numbering",
            "warn",
            "参考文献编号不连续",
            "参考文献编号应为从 1 开始的连续整数；当前编号存在缺号或重复。",
            {"section_index": 0},
            {"numbers": numbered},
        ))

    first_seen: list[int] = []
    for item in in_text:
        if item["kind"] != "numeric":
            continue
        for number in item["numbers"]:
            if number not in first_seen:
                first_seen.append(number)
    if first_seen != sorted(first_seen):
        issues.append(_issue(
            "citation.order",
            "info",
            "文内引用编号首次出现顺序不是升序",
            "顺序编码制通常要求文内引用按 [1]、[2]… 的先后顺序首次出现；"
            "当前顺序为 " + "、".join(f"[{number}]" for number in first_seen[:12]) + "。",
            {"block_index": in_text[0]["block_index"] if in_text else 0},
            {"first_seen": first_seen},
        ))

    unverified = [item for item in in_text if item["kind"] == "author_year" and item["status"] == "unverified"]
    if unverified:
        issues.append(_issue(
            "citation.author_year_unverified",
            "info",
            "部分作者-年份引用未能对应到文献条目",
            f"{len(unverified)} 处（作者，年份）引用没有在参考文献列表中找到同时匹配作者和年份的条目；"
            "中文文献建议人工确认。",
            {"block_index": unverified[0]["block_index"]},
            {"examples": [item["raw"] for item in unverified[:8]]},
        ))

    min_entries = int(references_config.get("min_entries") or 0)
    if ref_range and min_entries and len(references) < min_entries:
        issues.append(_issue(
            "citation.reference_count",
            "info",
            "参考文献数量少于模板建议",
            f"当前解析到 {len(references)} 条参考文献，模板建议至少 {min_entries} 条。"
            "如果条目因格式特殊未被识别，请人工确认。",
            {"section_index": 0},
            {"count": len(references), "min_entries": min_entries},
        ))

    # Keep individual citation issues bounded; a 1000-entry list should not
    # produce 1000 cards.
    if len(issues) > MAX_CITATION_ISSUES:
        issues = issues[:MAX_CITATION_ISSUES] + [_issue(
            "citation.truncated",
            "info",
            "引用问题较多，仅显示前一部分",
            f"共发现超过 {MAX_CITATION_ISSUES} 条引用问题，其余请参考引用清单人工核对。",
            {},
            {"shown": MAX_CITATION_ISSUES},
        )]

    return {
        "references": references,
        "in_text": in_text,
        "issues": issues,
        "reference_section_found": ref_range is not None,
    }

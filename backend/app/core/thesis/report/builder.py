"""Build the human-readable report and the final submission package.

Everything here is offline: no network calls, no model calls.  The report is
explicit about what was *not* checked so it can never be mistaken for a
guarantee of compliance.
"""
from __future__ import annotations

import csv
import html
import io
import json
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from docx import Document
from docx.oxml.ns import qn

from app.core.storage.user_storage import sanitize_filename

SEVERITY_LABEL = {"blocker": "阻断", "warn": "警告", "info": "提示"}
STATUS_LABEL = {
    "open": "待处理",
    "fixed": "已修复",
    "ignored": "已忽略",
    "matched": "已对应",
    "missing_reference": "缺少文献条目",
    "unverified": "需人工确认",
}
METADATA_LABEL = {
    "verified": "已核实",
    "partial": "部分匹配",
    "mismatch": "信息不符",
    "not_found": "未找到（不等于伪造）",
    "needs_review": "需人工确认",
    "no_doi": "无 DOI",
}
SUPPORT_LABEL = {
    "needs_review": "待确认",
    "supported": "支持",
    "partial": "部分支持",
    "unsupported": "不支持",
}
LIMITATIONS = [
    "本报告基于 DOCX 的结构与样式信息做确定性检查，不等同于学校的最终格式审查。",
    "没有做页面渲染级校验：分页、行距的视觉效果请在 Word/WPS 中确认。",
    "引用 L1 只做文本对照，不判断文献是否真实存在，也不判断引用是否恰当。",
    "引用 L2 只在你主动联网时运行，且只发送 DOI；未找到不代表文献是伪造的。",
    "引用 L3 只给出候选页码与原文，是否支持由你人工确认；扫描版 PDF 无法定位。",
    "中文文献、特殊格式条目与学校附加要求需要人工确认。",
    "本工具不会改写正文内容；已修复项均为页面/边距/标题样式等属性级修改。",
]


def _fmt(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def location_text(location: dict[str, Any] | None) -> str:
    location = location or {}
    if isinstance(location.get("section"), str):
        return str(location["section"])
    if isinstance(location.get("paragraph_index"), int):
        return f"第 {int(location['paragraph_index']) + 1} 段"
    if isinstance(location.get("text"), str) and location["text"]:
        return f"「{location['text']}」"
    return "全文"


def _report_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    return list(report.get("issues") or [])


def _citation_rows(citations: dict[str, Any] | None) -> tuple[list[dict], list[dict]]:
    if not citations:
        return [], []
    return list(citations.get("references") or []), list(citations.get("in_text") or [])


def _reference_metadata_text(item: dict[str, Any]) -> str:
    status = str(item.get("metadata_status") or "")
    if not status:
        return "未联网核验"
    label = METADATA_LABEL.get(status, status)
    detail = str((item.get("metadata") or {}).get("detail") or "")
    return f"{label}：{detail}" if detail else label


def _reference_evidence_text(item: dict[str, Any]) -> str:
    page = item.get("evidence_page")
    if not page:
        return "未定位"
    support = SUPPORT_LABEL.get(
        str(item.get("evidence_support") or "needs_review"), "待确认"
    )
    quote = str(item.get("evidence_quote") or "")
    head = f"第 {page} 页 · {support}"
    return f"{head}\n{quote}" if quote else head


def render_report_html(
    report: dict[str, Any],
    citations: dict[str, Any] | None,
    disclosures: list[dict[str, Any]],
    fixes: list[dict[str, Any]],
) -> str:
    e = html.escape
    project = report.get("project") or {}
    template = report.get("template") or {}
    document = report.get("document") or {}
    counts = report.get("counts") or {}
    issues = _report_rows(report)
    references, in_text = _citation_rows(citations)
    generated = report.get("generated_at")
    if isinstance(generated, datetime):
        generated_text = generated.strftime("%Y-%m-%d %H:%M:%S")
    else:
        generated_text = str(generated or "")

    issue_rows = "".join(
        "<tr>"
        f"<td>{e(SEVERITY_LABEL.get(str(issue.get('severity')), str(issue.get('severity'))))}</td>"
        f"<td><code>{e(str(issue.get('rule_id') or ''))}</code></td>"
        f"<td>{e(str(issue.get('title') or ''))}<br><span class='muted'>{e(str(issue.get('detail') or ''))}</span></td>"
        f"<td>{e(location_text(issue.get('location')))}</td>"
        f"<td>{e(STATUS_LABEL.get(str(issue.get('status')), str(issue.get('status') or '')))}</td>"
        f"<td>{e(str(issue.get('source') or ''))}</td>"
        "</tr>"
        for issue in issues
    ) or "<tr><td colspan='6' class='muted'>没有待处理问题。</td></tr>"

    reference_rows = "".join(
        "<tr>"
        f"<td>{e(_fmt(item.get('index')))}</td>"
        f"<td>{e(str(item.get('raw') or ''))}</td>"
        f"<td>{'是' if item.get('cited') else '否'}</td>"
        f"<td>{e(_reference_metadata_text(item))}</td>"
        f"<td>{e(_reference_evidence_text(item))}</td>"
        "</tr>"
        for item in references
    ) or "<tr><td colspan='5' class='muted'>未解析到参考文献列表。</td></tr>"

    in_text_rows = "".join(
        "<tr>"
        f"<td>{e(str(item.get('raw') or ''))}</td>"
        f"<td>{e('数字编号' if item.get('kind') == 'numeric' else '作者-年份')}</td>"
        f"<td>{e(STATUS_LABEL.get(str(item.get('status')), str(item.get('status') or '')))}</td>"
        f"<td>{e(str(item.get('block_index', '')))}</td>"
        "</tr>"
        for item in in_text
    ) or "<tr><td colspan='4' class='muted'>未识别到文内引用标注。</td></tr>"

    disclosure_rows = "".join(
        "<tr>"
        f"<td>{e(str(item.get('tool') or ''))} {e(str(item.get('tool_version') or ''))}</td>"
        f"<td>{e(str(item.get('stage') or ''))}</td>"
        f"<td>{e(str(item.get('purpose') or ''))}</td>"
        f"<td>{'是' if item.get('modified', True) else '否'}</td>"
        "</tr>"
        for item in disclosures
    ) or "<tr><td colspan='4' class='muted'>尚未登记 AI 使用记录。</td></tr>"

    fix_rows = "".join(
        "<tr>"
        f"<td><code>{e(str(item.get('rule_id') or ''))}</code></td>"
        f"<td>{e(str(item.get('fix_type') or ''))}</td>"
        f"<td>{'已撤销' if item.get('undone_at') else '已应用'}</td>"
        "</tr>"
        for item in fixes
    ) or "<tr><td colspan='3' class='muted'>没有修复记录。</td></tr>"

    limitations = "".join(f"<li>{e(item)}</li>" for item in LIMITATIONS)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>论文体检报告 · {e(str(project.get('title') or ''))}</title>
<style>
  body {{ font-family: "Noto Sans SC", "Microsoft YaHei", system-ui, sans-serif; margin: 32px; color: #1f2933; line-height: 1.6; }}
  h1 {{ font-size: 22px; margin: 0 0 4px; }}
  h2 {{ font-size: 16px; margin: 28px 0 8px; border-bottom: 1px solid #e4e7eb; padding-bottom: 4px; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
  th, td {{ border: 1px solid #d9dee4; padding: 6px 8px; text-align: left; vertical-align: top; }}
  th {{ background: #f5f7fa; }}
  td {{ white-space: pre-line; }}
  .muted {{ color: #7b8794; font-size: 12px; }}
  .meta {{ font-size: 13px; color: #52606d; }}
  code {{ font-family: ui-monospace, Consolas, monospace; font-size: 12px; }}
  ul {{ margin: 6px 0; padding-left: 20px; }}
</style>
</head>
<body>
<h1>论文体检报告</h1>
<p class="meta">论文：{e(str(project.get('title') or ''))} · 学校：{e(str(project.get('school') or '未填写'))} · 学位：{e(str(project.get('degree') or ''))}</p>
<p class="meta">模板：{e(str(template.get('name') or ''))}（{e(str(template.get('id') or ''))} · v{e(str(template.get('version') or ''))}） · 模板来源：{e(str(template.get('source') or ''))}</p>
<p class="meta">文档：{e(str(document.get('filename') or '未导入'))} · SHA-256：{e(str(document.get('sha256') or '—'))}</p>
<p class="meta">生成时间：{e(generated_text)} · 工具：Nova Agent 论文模式（本地规则引擎）</p>
<h2>概览</h2>
<p class="meta">阻断 {int(counts.get('blocker') or 0)} · 警告 {int(counts.get('warn') or 0)} · 提示 {int(counts.get('info') or 0)} · 合计 {int(counts.get('total') or 0)}</p>
<h2>问题清单</h2>
<table><thead><tr><th>级别</th><th>规则</th><th>问题</th><th>位置</th><th>状态</th><th>依据</th></tr></thead><tbody>{issue_rows}</tbody></table>
<h2>参考文献核对（L1 / L2 / L3）</h2>
<table><thead><tr><th>编号</th><th>条目</th><th>正文已引用</th><th>DOI 元数据（L2）</th><th>全文证据（L3）</th></tr></thead><tbody>{reference_rows}</tbody></table>
<h2>文内引用</h2>
<table><thead><tr><th>标注</th><th>类型</th><th>状态</th><th>段落</th></tr></thead><tbody>{in_text_rows}</tbody></table>
<h2>AI 使用登记</h2>
<table><thead><tr><th>工具</th><th>环节</th><th>用途</th><th>已修改</th></tr></thead><tbody>{disclosure_rows}</tbody></table>
<h2>修复记录</h2>
<table><thead><tr><th>规则</th><th>修复类型</th><th>状态</th></tr></thead><tbody>{fix_rows}</tbody></table>
<h2>局限与人工确认</h2>
<ul>{limitations}</ul>
</body>
</html>
"""


def _set_cjk_font(document: Any, name: str = "宋体") -> None:
    style = document.styles["Normal"]
    style.font.name = name
    r_pr = style.element.get_or_add_rPr()
    r_fonts = r_pr.find(qn("w:rFonts"))
    if r_fonts is None:
        from docx.oxml import OxmlElement

        r_fonts = OxmlElement("w:rFonts")
        r_pr.append(r_fonts)
    r_fonts.set(qn("w:eastAsia"), name)


def build_report_docx(
    report: dict[str, Any],
    citations: dict[str, Any] | None,
    disclosures: list[dict[str, Any]],
    fixes: list[dict[str, Any]],
) -> bytes:
    project = report.get("project") or {}
    template = report.get("template") or {}
    document = report.get("document") or {}
    counts = report.get("counts") or {}
    issues = _report_rows(report)
    references, in_text = _citation_rows(citations)
    generated = report.get("generated_at")
    if isinstance(generated, datetime):
        generated_text = generated.strftime("%Y-%m-%d %H:%M:%S")
    else:
        generated_text = str(generated or "")

    doc = Document()
    _set_cjk_font(doc)
    doc.add_heading("论文体检报告", level=0)
    doc.add_paragraph(f"论文：{project.get('title') or ''}")
    doc.add_paragraph(f"学校：{project.get('school') or '未填写'}　学位：{project.get('degree') or ''}")
    doc.add_paragraph(
        f"模板：{template.get('name') or ''}（{template.get('id') or ''} · "
        f"v{template.get('version') or ''}）"
    )
    doc.add_paragraph(f"模板来源：{template.get('source') or ''}")
    doc.add_paragraph(f"文档：{document.get('filename') or '未导入'}")
    doc.add_paragraph(f"SHA-256：{document.get('sha256') or '—'}")
    doc.add_paragraph(f"生成时间：{generated_text}")

    doc.add_heading("概览", level=1)
    doc.add_paragraph(
        f"阻断 {int(counts.get('blocker') or 0)} · 警告 {int(counts.get('warn') or 0)} · "
        f"提示 {int(counts.get('info') or 0)} · 合计 {int(counts.get('total') or 0)}"
    )

    doc.add_heading("问题清单", level=1)
    if issues:
        table = doc.add_table(rows=1, cols=5)
        table.style = "Table Grid"
        for cell, text in zip(
            table.rows[0].cells,
            ("级别", "规则", "问题", "位置", "状态"),
        ):
            cell.text = text
        for issue in issues:
            row = table.add_row().cells
            row[0].text = SEVERITY_LABEL.get(str(issue.get("severity")), str(issue.get("severity")))
            row[1].text = str(issue.get("rule_id") or "")
            row[2].text = f"{issue.get('title') or ''}\n{issue.get('detail') or ''}"
            row[3].text = location_text(issue.get("location"))
            row[4].text = STATUS_LABEL.get(str(issue.get("status")), str(issue.get("status") or ""))
    else:
        doc.add_paragraph("没有待处理问题。")

    doc.add_heading("参考文献核对（L1 / L2 / L3）", level=1)
    if references:
        table = doc.add_table(rows=1, cols=5)
        table.style = "Table Grid"
        for cell, text in zip(
            table.rows[0].cells,
            ("编号", "条目", "正文已引用", "DOI 元数据（L2）", "全文证据（L3）"),
        ):
            cell.text = text
        for item in references:
            row = table.add_row().cells
            row[0].text = _fmt(item.get("index"))
            row[1].text = str(item.get("raw") or "")
            row[2].text = "是" if item.get("cited") else "否"
            row[3].text = _reference_metadata_text(item)
            row[4].text = _reference_evidence_text(item)
    else:
        doc.add_paragraph("未解析到参考文献列表。")

    doc.add_heading("文内引用", level=1)
    if in_text:
        table = doc.add_table(rows=1, cols=3)
        table.style = "Table Grid"
        for cell, text in zip(table.rows[0].cells, ("标注", "类型", "状态")):
            cell.text = text
        for item in in_text:
            row = table.add_row().cells
            row[0].text = str(item.get("raw") or "")
            row[1].text = "数字编号" if item.get("kind") == "numeric" else "作者-年份"
            row[2].text = STATUS_LABEL.get(str(item.get("status")), str(item.get("status") or ""))
    else:
        doc.add_paragraph("未识别到文内引用标注。")

    doc.add_heading("AI 使用登记", level=1)
    if disclosures:
        table = doc.add_table(rows=1, cols=4)
        table.style = "Table Grid"
        for cell, text in zip(table.rows[0].cells, ("工具", "环节", "用途", "已修改")):
            cell.text = text
        for item in disclosures:
            row = table.add_row().cells
            row[0].text = f"{item.get('tool') or ''} {item.get('tool_version') or ''}".strip()
            row[1].text = str(item.get("stage") or "")
            row[2].text = str(item.get("purpose") or "")
            row[3].text = "是" if item.get("modified", True) else "否"
    else:
        doc.add_paragraph("尚未登记 AI 使用记录。")

    doc.add_heading("修复记录", level=1)
    if fixes:
        table = doc.add_table(rows=1, cols=3)
        table.style = "Table Grid"
        for cell, text in zip(table.rows[0].cells, ("规则", "修复类型", "状态")):
            cell.text = text
        for item in fixes:
            row = table.add_row().cells
            row[0].text = str(item.get("rule_id") or "")
            row[1].text = str(item.get("fix_type") or "")
            row[2].text = "已撤销" if item.get("undone_at") else "已应用"
    else:
        doc.add_paragraph("没有修复记录。")

    doc.add_heading("局限与人工确认", level=1)
    for item in LIMITATIONS:
        doc.add_paragraph(item, style="List Bullet")

    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def build_disclosure_docx(
    project: dict[str, Any],
    template: dict[str, Any],
    disclosures: list[dict[str, Any]],
) -> bytes:
    config = template.get("disclosure") or {}
    title = str(config.get("title") or "AI 工具使用声明")
    intro = str(config.get("intro") or "")
    doc = Document()
    _set_cjk_font(doc)
    doc.add_heading(title, level=0)
    doc.add_paragraph(f"论文题目：{project.get('title') or ''}")
    doc.add_paragraph("姓名/学号：____________________　　学院/专业：____________________")
    if intro:
        doc.add_paragraph(intro)
    if disclosures:
        table = doc.add_table(rows=1, cols=5)
        table.style = "Table Grid"
        for cell, text in zip(
            table.rows[0].cells,
            ("工具与版本", "使用环节", "用途", "生成内容/修改情况", "时间"),
        ):
            cell.text = text
        for item in disclosures:
            row = table.add_row().cells
            row[0].text = f"{item.get('tool') or ''} {item.get('tool_version') or ''}".strip()
            row[1].text = str(item.get("stage") or "")
            row[2].text = str(item.get("purpose") or "")
            detail = str(item.get("output") or "")
            if item.get("prompt"):
                detail = f"提示：{item['prompt']}\n{detail}"
            row[3].text = detail
            created = item.get("created_at")
            row[4].text = created.strftime("%Y-%m-%d") if isinstance(created, datetime) else str(created or "")
    else:
        doc.add_paragraph("本人未在论文写作过程中使用 AI 工具。")
        doc.add_paragraph("（如果使用过，请在上方补充；空白声明不代表未使用。）")
    doc.add_paragraph("本人确认以上信息真实完整，并对论文内容负责。")
    doc.add_paragraph("签名：____________________　　日期：____________________")
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def citations_csv(citations: dict[str, Any] | None) -> str:
    references, in_text = _citation_rows(citations)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "类型", "编号", "原文", "状态", "位置", "说明", "DOI/元数据（L2）", "全文证据（L3）",
    ])
    for item in references:
        writer.writerow([
            "参考文献",
            _fmt(item.get("index")),
            item.get("raw") or "",
            "正文已引用" if item.get("cited") else "未在正文引用",
            f"第 {int(item.get('block_index', 0)) + 1} 段" if item.get("block_index") is not None else "",
            "",
            _reference_metadata_text(item),
            _reference_evidence_text(item),
        ])
    for item in in_text:
        writer.writerow([
            "文内引用",
            ",".join(str(number) for number in item.get("numbers") or []),
            item.get("raw") or "",
            STATUS_LABEL.get(str(item.get("status")), str(item.get("status") or "")),
            f"第 {int(item.get('block_index', 0)) + 1} 段" if item.get("block_index") is not None else "",
            item.get("context") or "",
            "",
            "",
        ])
    return "﻿" + output.getvalue()


def write_export_package(
    export_dir: Path,
    base_name: str,
    *,
    fixed_docx: Path | None,
    report_html: str,
    report_docx: bytes,
    disclosure_docx: bytes,
    citations_csv_text: str,
    fixes: list[dict[str, Any]],
    project: dict[str, Any],
    template: dict[str, Any],
    document: dict[str, Any] | None,
) -> Path:
    safe_base = sanitize_filename(base_name).removesuffix(".docx") or "论文"
    export_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    package_root = export_dir / f"{safe_base}_定稿包_{stamp}"
    package_root.mkdir(parents=True, exist_ok=False)

    if fixed_docx is not None and fixed_docx.is_file():
        shutil.copy2(fixed_docx, package_root / f"{safe_base}_修复版.docx")
    (package_root / "论文体检报告.html").write_text(report_html, encoding="utf-8")
    (package_root / "论文体检报告.docx").write_bytes(report_docx)
    (package_root / "AI使用声明.docx").write_bytes(disclosure_docx)
    (package_root / "引用核验清单.csv").write_bytes(citations_csv_text.encode("utf-8"))
    (package_root / "修改记录.json").write_text(
        json.dumps(fixes, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    readme_lines = [
        f"# {project.get('title') or '论文'} · 定稿包",
        "",
        f"- 模板：{template.get('name')}（{template.get('id')} · v{template.get('version')}）",
        f"- 模板来源：{template.get('source')}",
        f"- 原始文档：{document.get('filename') if document else '未导入'}",
        f"- 原始 SHA-256：{document.get('sha256') if document else '—'}",
        f"- 生成时间：{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        "",
        "## 使用说明",
        "",
        "- `_修复版.docx` 只包含已确认应用的属性级修复；原文件仍保留在原位置。",
        "- 报告与引用清单是检查记录，不是学校出具的合规证明。",
        "- AI 使用声明需要在 Word 中补全姓名、学号并签名。",
        "- 目录、交叉引用等域请在 Word 中按 F9 更新。",
        "",
        "## 局限",
        "",
        *[f"- {item}" for item in LIMITATIONS],
        "",
    ]
    (package_root / "提交说明.md").write_text("\n".join(readme_lines), encoding="utf-8")

    zip_path = export_dir / f"{safe_base}_定稿包_{stamp}.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(package_root.iterdir()):
            archive.write(path, arcname=path.name)
    return zip_path


def write_stage_package(
    export_dir: Path,
    base_name: str,
    *,
    stage_docx: bytes | None,
    stage_markdown: str,
    disclosure_docx: bytes,
    stage_summary: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
    project: dict[str, Any],
) -> Path:
    """Package a thesis built from stage contents instead of an imported DOCX.

    The package always contains the Markdown source so the author can edit it
    elsewhere even when Pandoc/LibreOffice is unavailable.  A DOCX is included
    only when the conversion actually succeeded; a missing converter never
    produces an empty or fake Word file.
    """
    safe_base = sanitize_filename(base_name).removesuffix(".docx") or "论文"
    export_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    package_root = export_dir / f"{safe_base}_阶段稿包_{stamp}"
    package_root.mkdir(parents=True, exist_ok=False)

    (package_root / f"{safe_base}_阶段稿.md").write_text(stage_markdown, encoding="utf-8")
    if stage_docx:
        (package_root / f"{safe_base}_阶段稿.docx").write_bytes(stage_docx)
    (package_root / "AI使用声明.docx").write_bytes(disclosure_docx)
    (package_root / "阶段确认.json").write_text(
        json.dumps(
            {"stages": stage_summary, "warnings": warnings},
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    readme_lines = [
        f"# {project.get('title') or '论文'} · 阶段稿包",
        "",
        "- 内容来源：作者在各阶段填写的文字，按阶段顺序整理。",
        "- AI 使用声明需要在 Word 中补全姓名、学号并签名。",
        "- 这是阶段稿包，不是学校模板排版的最终论文；提交前请自行核对格式与内容。",
        "",
        "## 文件",
        "",
        "- `_阶段稿.docx`：由 Markdown 转换；转换工具不可用时只保留 Markdown。",
        "- `_阶段稿.md`：可继续编辑的源文件。",
        "- `阶段确认.json`：每个阶段的作者确认状态与导出时看到的警告。",
        "",
        "## 局限",
        "",
        *[f"- {item}" for item in LIMITATIONS],
        "",
    ]
    (package_root / "提交说明.md").write_text("\n".join(readme_lines), encoding="utf-8")

    zip_path = export_dir / f"{safe_base}_阶段稿包_{stamp}.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(package_root.iterdir()):
            archive.write(path, arcname=path.name)
    return zip_path

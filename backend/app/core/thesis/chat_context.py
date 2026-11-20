"""Bounded thesis context injected into a thesis-mode chat turn.

The agent keeps its normal tool stack (read/search/edit the linked project,
run commands when allowed).  This module only adds the facts it cannot infer
from the repository: which thesis it is helping with, what the latest checks
found, and which references the user actually has.
"""
from __future__ import annotations

import json

import structlog

from app.core.thesis import service
from app.db import query

logger = structlog.get_logger()

MAX_CHARS = 6500
MAX_REFERENCES = 30
MAX_ISSUES = 10
MAX_OUTLINE = 50

WRITING_RULES = """## 论文模式写作约定（必须遵守）
- 你是论文写作与工程理解助手，不是代写工具：可以帮用户梳理项目、生成提纲、起草章节草稿、解释代码与数据流，但整篇论文必须由用户本人核对、修改并署名。
- 技术事实只能来自当前关联仓库的代码/文档，或用户在本轮提供的材料。引用实现时写清 `文件路径:行号`；不确定就写「待核实」，不要猜测。
- 参考文献只能使用下面列出的条目，沿用论文里的编号（如 `[3]`）。绝不编造文献、DOI、数据或实验结果；需要新文献时提醒用户自己补充。
- 生成任何正文时明确标注「AI 草稿，需本人核对与改写」，并提醒用户把本次 AI 参与记入「AI 使用声明」。
- 不提供降重、规避 AIGC 检测、代写或伪造数据的方法；遇到这类请求要说明边界并给出合规替代方案。
- 修改本地项目文件属于开发行为：遵循当前权限模式；不要擅自改动论文 DOCX 或用户未点名的文件。
- 默认用中文回答，结构清晰；给出可选提纲时说明每章对应项目的哪些模块或证据。"""


def _clip(text: str, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit] + "…"


async def _repo_line(user_id: int, repo_id: str | None) -> str:
    if not repo_id:
        return ""
    rows = await query(
        "SELECT name, root_path, source FROM repos WHERE id = %s AND user_id = %s",
        (repo_id, user_id),
    )
    if not rows:
        return ""
    name, root_path, source = rows[0]
    return f"- 关联工程项目：{name}（repo_id: {repo_id}，路径: {root_path}，来源: {source}）"


async def _document_lines(user_id: int, project_id: str) -> list[str]:
    documents = await service.list_documents(user_id, project_id)
    if not documents:
        return ["- 尚未导入 DOCX 论文"]
    document = documents[0]
    stats = document.get("stats") or {}
    lines = [
        f"- 最新 DOCX：{document['filename']}（{document.get('status')}，"
        f"{stats.get('paragraph_count', 0)} 段 / {stats.get('heading_count', 0)} 标题 / "
        f"{stats.get('char_count', 0)} 字符）"
    ]
    outline_rows = await query(
        "SELECT document_model->'outline' FROM thesis_documents "
        "WHERE id = %s AND user_id = %s",
        (document["id"], user_id),
    )
    outline = outline_rows[0][0] if outline_rows else None
    if isinstance(outline, str):
        try:
            outline = json.loads(outline)
        except ValueError:
            outline = None
    if isinstance(outline, list) and outline:
        lines.append("- 现有提纲：")
        for node in outline[:MAX_OUTLINE]:
            if not isinstance(node, dict):
                continue
            level = int(node.get("level") or 1)
            text = str(node.get("text") or "").strip()
            if text:
                lines.append(f"  {'#' * min(level, 6)} {text}")
    return lines


async def _issue_lines(user_id: int, project_id: str) -> list[str]:
    issues = await service.list_issues(user_id, project_id, status="open")
    if not issues:
        return ["- 当前没有未处理的体检问题"]
    lines = [f"- 未处理体检问题（共 {len(issues)} 条，列出前 {min(len(issues), MAX_ISSUES)} 条）："]
    for issue in issues[:MAX_ISSUES]:
        location = issue.get("location") or {}
        where = (
            location.get("section")
            or (
                f"第 {int(location['paragraph_index']) + 1} 段"
                if isinstance(location.get("paragraph_index"), int)
                else "全文"
            )
        )
        lines.append(
            f"  - [{issue.get('severity')}] {issue.get('title')}"
            f"（{where}，规则 {issue.get('rule_id')}）"
        )
    return lines


async def _reference_lines(user_id: int, project_id: str) -> list[str]:
    citations = await service.get_citations(user_id, project_id)
    references = list((citations or {}).get("references") or [])
    if not references:
        return ["- 参考文献：尚未运行引用核对"]
    lines = [f"- 参考文献清单（共 {len(references)} 条，列出前 {min(len(references), MAX_REFERENCES)} 条）："]
    for item in references[:MAX_REFERENCES]:
        index = item.get("index")
        prefix = f"[{index}] " if index is not None else ""
        status = item.get("metadata_status") or item.get("status") or ""
        title = ""
        metadata = item.get("metadata") or {}
        if isinstance(metadata, dict):
            title = str(metadata.get("title") or "")
        suffix = f"（L2: {status}）" if status and status != "no_doi" else ""
        lines.append(f"  - {prefix}{_clip(str(item.get('raw') or ''), 240)}{suffix}")
        if title:
            lines.append(f"    Crossref 题名：{_clip(title, 200)}")
    return lines


async def build_thesis_context(user_id: int, project_id: str) -> str:
    """Return a bounded markdown block, or ``""`` when the project is gone."""
    try:
        project = await service.get_project(user_id, project_id)
        if not project:
            return ""
        template = service.get_template(project["template_id"])
        lines = [
            "## 当前论文项目",
            f"- 题目：{project['title']}",
            f"- 学校 / 层次：{project.get('school') or '未填写'} / {project.get('degree')}",
            f"- 模板：{template.get('name', project['template_id'])}"
            f"（版本 {template.get('version', '—')}"
            f"{'，示例模板' if template.get('is_sample') else ''}）",
            f"- 项目说明：{_clip(project.get('source_notes') or '未填写', 1200)}",
        ]
        repo_line = await _repo_line(user_id, project.get("source_repo_id"))
        if repo_line:
            lines.append(repo_line)
        else:
            lines.append("- 尚未关联工程项目；涉及代码的问题请让用户先选择项目。")
        lines.extend(await _document_lines(user_id, project_id))
        lines.extend(await _issue_lines(user_id, project_id))
        lines.extend(await _reference_lines(user_id, project_id))
        context = WRITING_RULES + "\n\n" + "\n".join(lines)
        return _clip(context, MAX_CHARS)
    except Exception as exc:  # noqa: BLE001 - context is best-effort
        logger.warning("thesis_context_failed", project_id=project_id, error=str(exc))
        return ""


__all__ = ["build_thesis_context", "WRITING_RULES"]

"""Persistence and orchestration for thesis projects."""
from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog
from fastapi import UploadFile

from app.config import settings
from app.core.storage.user_storage import sanitize_filename, thesis_container
from app.core.thesis.citations.extract import audit_citations
from app.core.thesis.citations.fulltext import (
    extract_pdf_pages,
    locate_references,
)
from app.core.thesis.citations.metadata import (
    cache_is_fresh,
    classify_reference,
    extract_doi,
    fetch_dois,
)
from app.core.thesis.docx.parser import file_sha256, parse_docx
from app.core.thesis.docx.patcher import (
    SUPPORTED_FIX_TYPES,
    apply_fix_file,
    preview_fix,
)
from app.core.thesis.models import DocumentModel
from app.core.thesis.report.builder import (
    build_disclosure_docx,
    build_report_docx,
    citations_csv,
    render_report_html,
    write_export_package,
)
from app.core.thesis.rules.builtin import GENERIC_TEMPLATE, get_template, list_templates
from app.core.thesis.rules.engine import run_rules
from app.db import execute, query, transaction

logger = structlog.get_logger()

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

PROJECT_COLUMNS = """
    p.id::text, p.title, p.school, p.degree, p.template_id, p.status,
    p.created_at, p.updated_at,
    (SELECT count(*) FROM thesis_documents d WHERE d.project_id = p.id) AS document_count,
    (SELECT count(*) FROM thesis_issues i WHERE i.project_id = p.id AND i.status = 'open')
        AS open_issue_count
"""

DOCUMENT_COLUMNS = """
    d.id::text, d.project_id::text, d.filename, d.sha256, d.size, d.mime,
    d.status, d.parse_error, d.stats, d.created_at, d.updated_at,
    d.working_path, d.working_sha256, d.version
"""

ISSUE_COLUMNS = """
    i.id::text, i.project_id::text, i.document_id::text, i.rule_id, i.category,
    i.severity, i.title, i.detail, i.location, i.evidence, i.status, i.created_at,
    i.fix_type, i.fix_payload, i.source, i.template_version, i.confidence, i.updated_at
"""

FIX_COLUMNS = """
    f.id::text, f.project_id::text, f.document_id::text, f.issue_id::text,
    f.rule_id, f.fix_type, f.before, f.after, f.applied_at, f.undone_at
"""

CITATION_COLUMNS = """
    c.id::text, c.project_id::text, c.document_id::text, c.kind, c.raw,
    c.normalized, c.status, c.confidence, c.created_at,
    c.doi, c.metadata_status, c.metadata, c.metadata_fetched_at
"""

DISCLOSURE_COLUMNS = """
    d.id::text, d.project_id::text, d.tool, d.tool_version, d.purpose,
    d.stage, d.prompt, d.output, d.modified, d.created_at
"""

REFERENCE_PDF_COLUMNS = """
    r.id::text, r.project_id::text, r.filename, r.sha256, r.size,
    r.page_count, r.created_at
"""

EVIDENCE_COLUMNS = """
    e.id::text, e.project_id::text, e.document_id::text, e.reference_index,
    e.reference_raw, e.pdf_id::text, r.filename, e.page, e.quote, e.score,
    e.method, e.support, e.note, e.created_at, e.updated_at
"""

EVIDENCE_SUPPORT = ("needs_review", "supported", "partial", "unsupported")


def _valid_uuid(value: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (AttributeError, TypeError, ValueError) as exc:
        raise LookupError("论文项目不存在") from exc


def _project_row(row: tuple) -> dict[str, Any]:
    return {
        "id": str(row[0]),
        "title": row[1],
        "school": row[2] or "",
        "degree": row[3] or "undergraduate",
        "template_id": row[4] or GENERIC_TEMPLATE["id"],
        "status": row[5] or "draft",
        "created_at": row[6],
        "updated_at": row[7],
        "document_count": int(row[8] or 0),
        "open_issue_count": int(row[9] or 0),
    }


def _document_row(row: tuple) -> dict[str, Any]:
    return {
        "id": str(row[0]),
        "project_id": str(row[1]),
        "filename": row[2],
        "sha256": row[3],
        "size": int(row[4] or 0),
        "mime": row[5] or DOCX_MIME,
        "status": row[6],
        "parse_error": row[7],
        "stats": row[8] or {},
        "created_at": row[9],
        "updated_at": row[10],
        "version": int(row[13] or 1),
        "has_working_copy": bool(row[11]),
        "outline": [],
        "warnings": [],
    }


def _issue_row(row: tuple) -> dict[str, Any]:
    fix_type = row[12]
    return {
        "id": str(row[0]),
        "project_id": str(row[1]),
        "document_id": str(row[2]),
        "rule_id": row[3],
        "category": row[4],
        "severity": row[5],
        "title": row[6],
        "detail": row[7] or "",
        "location": row[8] or {},
        "evidence": row[9] or {},
        "status": row[10],
        "created_at": row[11],
        "fix_type": fix_type,
        "fix_available": bool(fix_type),
        "fix_payload": row[13] or {},
        "source": row[14] or "",
        "template_version": row[15] or "",
        "confidence": row[16] or "high",
        "updated_at": row[17],
    }


def _fix_row(row: tuple) -> dict[str, Any]:
    return {
        "id": str(row[0]),
        "project_id": str(row[1]),
        "document_id": str(row[2]),
        "issue_id": str(row[3]) if row[3] else None,
        "rule_id": row[4] or "",
        "fix_type": row[5] or "",
        "before": row[6] or {},
        "after": row[7] or {},
        "applied_at": row[8],
        "undone_at": row[9],
    }


def _citation_row(row: tuple) -> dict[str, Any]:
    return {
        "id": str(row[0]),
        "project_id": str(row[1]),
        "document_id": str(row[2]),
        "kind": row[3],
        "raw": row[4] or "",
        "normalized": row[5] or {},
        "status": row[6] or "unverified",
        "confidence": row[7] or "medium",
        "created_at": row[8],
        "doi": row[9] or "",
        "metadata_status": row[10] or "",
        "metadata": row[11] or {},
        "metadata_fetched_at": row[12],
    }


def _reference_pdf_row(row: tuple) -> dict[str, Any]:
    return {
        "id": str(row[0]),
        "project_id": str(row[1]),
        "filename": row[2],
        "sha256": row[3] or "",
        "size": int(row[4] or 0),
        "page_count": int(row[5] or 0),
        "created_at": row[6],
    }


def _evidence_row(row: tuple) -> dict[str, Any]:
    return {
        "id": str(row[0]),
        "project_id": str(row[1]),
        "document_id": str(row[2]) if row[2] else None,
        "reference_index": int(row[3]) if row[3] is not None else None,
        "reference_raw": row[4] or "",
        "pdf_id": str(row[5]) if row[5] else None,
        "pdf_filename": row[6] or "",
        "page": int(row[7]) if row[7] is not None else None,
        "quote": row[8] or "",
        "score": float(row[9] or 0),
        "method": row[10] or "",
        "support": row[11] or "needs_review",
        "note": row[12] or "",
        "created_at": row[13],
        "updated_at": row[14],
    }


def _disclosure_row(row: tuple) -> dict[str, Any]:
    return {
        "id": str(row[0]),
        "project_id": str(row[1]),
        "tool": row[2] or "",
        "tool_version": row[3] or "",
        "purpose": row[4] or "",
        "stage": row[5] or "",
        "prompt": row[6] or "",
        "output": row[7] or "",
        "modified": bool(row[8]),
        "created_at": row[9],
    }


def _counts(issues: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"blocker": 0, "warn": 0, "info": 0, "total": len(issues)}
    for issue in issues:
        severity = str(issue.get("severity") or "info")
        if severity in counts:
            counts[severity] += 1
    return counts


def _template_public(template: dict[str, Any]) -> dict[str, Any]:
    return next(
        (item for item in list_templates() if item["id"] == template["id"]),
        {
            "id": template["id"],
            "name": template["name"],
            "description": template["description"],
            "source": template["source"],
            "version": template.get("version", ""),
            "degree": template["degree"],
            "is_sample": template.get("is_sample", True),
        },
    )


async def list_projects(user_id: int, limit: int = 100) -> list[dict[str, Any]]:
    rows = await query(
        f"SELECT {PROJECT_COLUMNS} FROM thesis_projects p "
        "WHERE p.user_id = %s ORDER BY p.updated_at DESC LIMIT %s",
        (user_id, limit),
    )
    return [_project_row(row) for row in rows]


async def get_project(user_id: int, project_id: str) -> dict[str, Any] | None:
    project_id = _valid_uuid(project_id)
    rows = await query(
        f"SELECT {PROJECT_COLUMNS} FROM thesis_projects p "
        "WHERE p.id = %s AND p.user_id = %s",
        (project_id, user_id),
    )
    return _project_row(rows[0]) if rows else None


async def create_project(
    user_id: int,
    *,
    title: str,
    school: str = "",
    degree: str = "undergraduate",
    template_id: str = GENERIC_TEMPLATE["id"],
) -> dict[str, Any]:
    template = get_template(template_id)
    project_id = str(uuid.uuid4())
    await execute(
        "INSERT INTO thesis_projects "
        "(id, user_id, title, school, degree, template_id, status) "
        "VALUES (%s, %s, %s, %s, %s, %s, 'draft')",
        (project_id, user_id, title.strip(), school.strip(), degree, template["id"]),
    )
    project = await get_project(user_id, project_id)
    if not project:
        raise RuntimeError("创建论文项目失败")
    return project


async def update_project(
    user_id: int,
    project_id: str,
    *,
    title: str | None = None,
    school: str | None = None,
    degree: str | None = None,
    template_id: str | None = None,
) -> dict[str, Any] | None:
    project_id = _valid_uuid(project_id)
    assignments: list[str] = []
    params: list[Any] = []
    if title is not None:
        assignments.append("title = %s")
        params.append(title.strip())
    if school is not None:
        assignments.append("school = %s")
        params.append(school.strip())
    if degree is not None:
        assignments.append("degree = %s")
        params.append(degree)
    if template_id is not None:
        assignments.append("template_id = %s")
        params.append(get_template(template_id)["id"])
    if assignments:
        assignments.append("updated_at = now()")
        params.extend([project_id, user_id])
        await execute(
            f"UPDATE thesis_projects SET {', '.join(assignments)} "
            "WHERE id = %s AND user_id = %s",
            tuple(params),
        )
        if template_id is not None:
            # Old results were produced against a different template.
            await execute(
                "DELETE FROM thesis_issues WHERE project_id = %s AND user_id = %s",
                (project_id, user_id),
            )
            await execute(
                "DELETE FROM thesis_citations WHERE project_id = %s AND user_id = %s",
                (project_id, user_id),
            )
            await execute(
                "DELETE FROM thesis_citation_evidence "
                "WHERE project_id = %s AND user_id = %s",
                (project_id, user_id),
            )
    return await get_project(user_id, project_id)


async def delete_project(user_id: int, project_id: str) -> bool:
    project_id = _valid_uuid(project_id)
    project = await get_project(user_id, project_id)
    if not project:
        return False
    await execute(
        "DELETE FROM thesis_projects WHERE id = %s AND user_id = %s",
        (project_id, user_id),
    )
    await asyncio.to_thread(
        shutil.rmtree, thesis_container(user_id, project_id), True
    )
    return True


async def list_documents(user_id: int, project_id: str) -> list[dict[str, Any]]:
    project_id = _valid_uuid(project_id)
    rows = await query(
        f"SELECT {DOCUMENT_COLUMNS} FROM thesis_documents d "
        "WHERE d.project_id = %s AND d.user_id = %s ORDER BY d.created_at DESC",
        (project_id, user_id),
    )
    return [_document_row(row) for row in rows]


async def get_document(
    user_id: int,
    document_id: str,
    *,
    include_model: bool = False,
) -> dict[str, Any] | None:
    document_id = _valid_uuid(document_id)
    columns = DOCUMENT_COLUMNS + (", d.document_model" if include_model else "")
    rows = await query(
        f"SELECT {columns} FROM thesis_documents d "
        "WHERE d.id = %s AND d.user_id = %s",
        (document_id, user_id),
    )
    if not rows:
        return None
    row = rows[0]
    document = _document_row(row[:14])
    if include_model and row[14]:
        model = DocumentModel.from_dict(row[14])
        document["outline"] = model.outline
        document["warnings"] = model.warnings
    return document


async def _latest_document_full(user_id: int, project_id: str) -> dict[str, Any] | None:
    """Latest parsed document plus storage paths and the document model."""
    rows = await query(
        f"SELECT {DOCUMENT_COLUMNS}, d.storage_path, d.document_model "
        "FROM thesis_documents d "
        "WHERE d.project_id = %s AND d.user_id = %s AND d.status = 'parsed' "
        "ORDER BY d.created_at DESC LIMIT 1",
        (project_id, user_id),
    )
    if not rows:
        return None
    row = rows[0]
    return {
        "document": _document_row(row[:14]),
        "storage_path": row[14],
        "working_path": row[11],
        "document_model": row[15],
    }


async def import_document(
    user_id: int,
    project_id: str,
    upload: UploadFile,
) -> dict[str, Any]:
    project_id = _valid_uuid(project_id)
    project = await get_project(user_id, project_id)
    if not project:
        raise LookupError("论文项目不存在")

    filename = sanitize_filename(upload.filename or "thesis.docx")
    if not filename.lower().endswith(".docx"):
        raise ValueError("只支持 .docx 文件；.doc 请先在 Word/WPS 中另存为 .docx")

    dest_dir = thesis_container(user_id, project_id)
    await asyncio.to_thread(lambda: dest_dir.mkdir(parents=True, exist_ok=True))
    document_id = str(uuid.uuid4())
    final_path = dest_dir / f"{document_id}.docx"
    tmp_path = dest_dir / f".{document_id}.uploading"
    max_bytes = settings.attachment_max_mb * 1024 * 1024
    total = 0
    digest = hashlib.sha256()

    try:
        with open(tmp_path, "wb") as out:
            while chunk := await upload.read(1024 * 1024):
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError(f"文件超过上限（{settings.attachment_max_mb}MB）")
                digest.update(chunk)
                out.write(chunk)
        if total == 0:
            raise ValueError("文件为空")
        if not zipfile.is_zipfile(tmp_path):
            raise ValueError("不是有效的 DOCX 文件（zip 结构损坏）")
        with zipfile.ZipFile(tmp_path) as archive:
            if "word/document.xml" not in archive.namelist():
                raise ValueError("DOCX 缺少 word/document.xml")
        tmp_path.replace(final_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise

    sha256 = digest.hexdigest()
    status = "parsed"
    parse_error: str | None = None
    model_json: str | None = None
    stats: dict[str, Any] = {}
    try:
        model = await asyncio.to_thread(
            parse_docx,
            final_path,
            filename=filename,
            sha256=sha256,
            size=total,
        )
        model_json = json.dumps(model.to_dict(), ensure_ascii=False)
        stats = model.stats
    except Exception as exc:  # noqa: BLE001 - parser failures become document state
        logger.warning(
            "thesis_docx_parse_failed",
            user_id=user_id,
            project_id=project_id,
            error=str(exc),
        )
        status = "failed"
        parse_error = str(exc)[:2000]

    try:
        await execute(
            "INSERT INTO thesis_documents "
            "(id, project_id, user_id, filename, storage_path, sha256, size, mime, "
            "status, parse_error, document_model, stats) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                document_id, project_id, user_id, filename, str(final_path),
                sha256, total, DOCX_MIME, status, parse_error,
                model_json, json.dumps(stats, ensure_ascii=False),
            ),
        )
        await execute(
            "UPDATE thesis_projects SET status = %s, updated_at = now() "
            "WHERE id = %s AND user_id = %s",
            (status if status == "parsed" else "failed", project_id, user_id),
        )
        # New source document invalidates previous results and citation rows.
        await execute(
            "DELETE FROM thesis_issues WHERE project_id = %s AND user_id = %s",
            (project_id, user_id),
        )
        await execute(
            "DELETE FROM thesis_citations WHERE project_id = %s AND user_id = %s",
            (project_id, user_id),
        )
        await execute(
            "DELETE FROM thesis_citation_evidence "
            "WHERE project_id = %s AND user_id = %s",
            (project_id, user_id),
        )
    except Exception:
        final_path.unlink(missing_ok=True)
        raise

    document = await get_document(user_id, document_id)
    if not document:
        raise RuntimeError("保存论文文档失败")
    return document


async def list_issues(
    user_id: int,
    project_id: str,
    *,
    status: str = "open",
) -> list[dict[str, Any]]:
    project_id = _valid_uuid(project_id)
    clauses = ["i.project_id = %s", "i.user_id = %s"]
    params: list[Any] = [project_id, user_id]
    if status and status != "all":
        clauses.append("i.status = %s")
        params.append(status)
    rows = await query(
        f"SELECT {ISSUE_COLUMNS} FROM thesis_issues i "
        f"WHERE {' AND '.join(clauses)} "
        "ORDER BY CASE i.severity WHEN 'blocker' THEN 0 WHEN 'warn' THEN 1 ELSE 2 END, "
        "i.created_at, i.id",
        tuple(params),
    )
    return [_issue_row(row) for row in rows]


def _issue_statements(
    user_id: int,
    project_id: str,
    document_id: str,
    drafts: list[Any],
) -> list[tuple[str, tuple]]:
    statements: list[tuple[str, tuple]] = []
    for draft in drafts:
        statements.append((
            "INSERT INTO thesis_issues "
            "(id, project_id, document_id, user_id, rule_id, category, severity, "
            "title, detail, location, evidence, status, fix_type, fix_payload, "
            "source, template_version, confidence) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'open', "
            "%s, %s, %s, %s, %s)",
            (
                str(uuid.uuid4()), project_id, document_id, user_id,
                draft.rule_id, draft.category, draft.severity, draft.title,
                draft.detail, json.dumps(draft.location, ensure_ascii=False),
                json.dumps(draft.evidence, ensure_ascii=False),
                draft.fix_type,
                json.dumps(draft.fix_payload, ensure_ascii=False),
                draft.source[:300], draft.template_version[:40], draft.confidence,
            ),
        ))
    return statements


def _citation_statements(
    user_id: int,
    project_id: str,
    document_id: str,
    audit: dict[str, Any],
) -> list[tuple[str, tuple]]:
    statements: list[tuple[str, tuple]] = [
        ("DELETE FROM thesis_citations WHERE project_id = %s AND user_id = %s",
         (project_id, user_id)),
    ]
    for entry in audit.get("references") or []:
        statements.append((
            "INSERT INTO thesis_citations "
            "(id, project_id, document_id, user_id, kind, raw, normalized, "
            "status, confidence) VALUES (%s, %s, %s, %s, 'reference', %s, %s, %s, %s)",
            (
                str(uuid.uuid4()), project_id, document_id, user_id,
                str(entry.get("raw") or "")[:500],
                json.dumps(entry, ensure_ascii=False),
                "cited" if entry.get("cited") else "uncited",
                "medium",
            ),
        ))
    for item in audit.get("in_text") or []:
        statements.append((
            "INSERT INTO thesis_citations "
            "(id, project_id, document_id, user_id, kind, raw, normalized, "
            "status, confidence) VALUES (%s, %s, %s, %s, 'in_text', %s, %s, %s, %s)",
            (
                str(uuid.uuid4()), project_id, document_id, user_id,
                str(item.get("raw") or "")[:500],
                json.dumps(item, ensure_ascii=False),
                str(item.get("status") or "unverified"),
                "medium",
            ),
        ))
    return statements


async def scan_project(
    user_id: int,
    project_id: str,
    *,
    template_id: str | None = None,
) -> dict[str, Any]:
    project_id = _valid_uuid(project_id)
    project = await get_project(user_id, project_id)
    if not project:
        raise LookupError("论文项目不存在")
    full = await _latest_document_full(user_id, project_id)
    if not full:
        raise ValueError("请先导入一份可解析的 DOCX")
    document_id = full["document"]["id"]
    model_data = full["document_model"]
    if not model_data:
        raise ValueError("文档模型为空，请重新导入后重试")

    model = DocumentModel.from_dict(model_data)
    template = get_template(template_id or project["template_id"])
    audit = audit_citations(model, template)
    drafts = run_rules(model, template["id"], citation_audit=audit)

    statements: list[tuple[str, tuple]] = [
        ("DELETE FROM thesis_issues WHERE project_id = %s AND user_id = %s",
         (project_id, user_id)),
    ]
    statements.extend(_issue_statements(user_id, project_id, document_id, drafts))
    statements.extend(_citation_statements(user_id, project_id, document_id, audit))
    await transaction(statements)
    issues = await list_issues(user_id, project_id)
    return {
        "project_id": project_id,
        "document_id": document_id,
        "template_id": template["id"],
        "issues": issues,
        "counts": _counts(issues),
        "scanned_at": datetime.now(timezone.utc),
    }


async def set_issue_status(user_id: int, issue_id: str, status: str) -> dict[str, Any] | None:
    if status not in ("open", "ignored"):
        raise ValueError("只支持 open / ignored")
    issue_id = _valid_uuid(issue_id)
    rows = await execute(
        "UPDATE thesis_issues SET status = %s, updated_at = now() "
        "WHERE id = %s AND user_id = %s RETURNING id",
        (status, issue_id, user_id),
    )
    if not rows:
        return None
    return await get_issue(user_id, issue_id)


async def get_issue(user_id: int, issue_id: str) -> dict[str, Any] | None:
    rows = await query(
        f"SELECT {ISSUE_COLUMNS} FROM thesis_issues i "
        "WHERE i.id = %s AND i.user_id = %s",
        (issue_id, user_id),
    )
    return _issue_row(rows[0]) if rows else None


async def _issue_with_document(user_id: int, issue_id: str) -> dict[str, Any]:
    issue_id = _valid_uuid(issue_id)
    rows = await query(
        f"SELECT {ISSUE_COLUMNS}, d.storage_path, d.working_path, d.document_model, "
        "d.status, p.title "
        "FROM thesis_issues i "
        "JOIN thesis_documents d ON d.id = i.document_id "
        "JOIN thesis_projects p ON p.id = i.project_id "
        "WHERE i.id = %s AND i.user_id = %s AND d.user_id = %s",
        (issue_id, user_id),
    )
    if not rows:
        raise LookupError("论文问题不存在")
    row = rows[0]
    return {
        "issue": _issue_row(row[:18]),
        "storage_path": row[18],
        "working_path": row[19],
        "document_model": row[20],
        "document_status": row[21],
        "project_title": row[22],
    }


async def list_fixes(user_id: int, project_id: str) -> list[dict[str, Any]]:
    project_id = _valid_uuid(project_id)
    rows = await query(
        f"SELECT {FIX_COLUMNS} FROM thesis_fixes f "
        "WHERE f.project_id = %s AND f.user_id = %s ORDER BY f.applied_at DESC",
        (project_id, user_id),
    )
    return [_fix_row(row) for row in rows]


async def preview_issue_fix(user_id: int, issue_id: str) -> dict[str, Any]:
    record = await _issue_with_document(user_id, issue_id)
    issue = record["issue"]
    if issue["status"] != "open":
        raise ValueError("只有待处理的问题可以修复")
    fix_type = issue.get("fix_type")
    if not fix_type or fix_type not in SUPPORTED_FIX_TYPES:
        raise ValueError("该问题暂不支持自动修复，请按提示手动处理")
    source = Path(record["working_path"] or record["storage_path"])
    if not source.is_file():
        raise ValueError("文档文件不存在，请重新导入")
    model = (
        DocumentModel.from_dict(record["document_model"])
        if record["document_model"]
        else await asyncio.to_thread(parse_docx, source)
    )
    result = await asyncio.to_thread(
        preview_fix,
        source,
        fix_type,
        issue.get("fix_payload") or {},
        before_model=model,
    )
    return {"issue_id": issue["id"], **result}


async def _post_fix_result(
    user_id: int,
    project_id: str,
    issue_id: str,
    fix_id: str,
    document: dict[str, Any],
) -> dict[str, Any]:
    issue = await get_issue(user_id, issue_id)
    fix = await _get_fix(user_id, fix_id)
    open_issues = await list_issues(user_id, project_id)
    return {
        "issue": issue,
        "fix": fix,
        "document": document,
        "remaining_counts": _counts(open_issues),
    }


async def _get_fix(user_id: int, fix_id: str) -> dict[str, Any] | None:
    rows = await query(
        f"SELECT {FIX_COLUMNS} FROM thesis_fixes f "
        "WHERE f.id = %s AND f.user_id = %s",
        (fix_id, user_id),
    )
    return _fix_row(rows[0]) if rows else None


async def apply_issue_fix(user_id: int, issue_id: str) -> dict[str, Any]:
    record = await _issue_with_document(user_id, issue_id)
    issue = record["issue"]
    if record["document_status"] != "parsed":
        raise ValueError("当前文档未成功解析，不能修复")
    if issue["status"] != "open":
        raise ValueError("只有待处理的问题可以修复")
    fix_type = issue.get("fix_type")
    if not fix_type or fix_type not in SUPPORTED_FIX_TYPES:
        raise ValueError("该问题暂不支持自动修复，请按提示手动处理")

    project_id = issue["project_id"]
    document_id = issue["document_id"]
    container = thesis_container(user_id, project_id)
    working = container / "working.docx"
    versions = container / "versions"
    await asyncio.to_thread(lambda: versions.mkdir(parents=True, exist_ok=True))
    if not working.is_file():
        source = Path(record["storage_path"])
        if not source.is_file():
            raise ValueError("原始文档不存在，请重新导入")
        await asyncio.to_thread(shutil.copy2, source, working)

    model = (
        DocumentModel.from_dict(record["document_model"])
        if record["document_model"]
        else await asyncio.to_thread(parse_docx, working)
    )
    fix_id = str(uuid.uuid4())
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    backup = versions / f"{stamp}-{fix_id}.docx"
    await asyncio.to_thread(shutil.copy2, working, backup)
    patched = container / f".{fix_id}.patched"
    try:
        result = await asyncio.to_thread(
            apply_fix_file,
            working,
            patched,
            fix_type,
            issue.get("fix_payload") or {},
            before_model=model,
        )
        patched.replace(working)
    except Exception:
        patched.unlink(missing_ok=True)
        backup.unlink(missing_ok=True)
        raise

    updated_model: DocumentModel = result["model"]
    sha256 = await asyncio.to_thread(file_sha256, working)
    await transaction([
        (
            "UPDATE thesis_documents SET working_path = %s, working_sha256 = %s, "
            "version = version + 1, document_model = %s, stats = %s, "
            "updated_at = now() WHERE id = %s AND user_id = %s",
            (
                str(working), sha256,
                json.dumps(updated_model.to_dict(), ensure_ascii=False),
                json.dumps(updated_model.stats, ensure_ascii=False),
                document_id, user_id,
            ),
        ),
        (
            "INSERT INTO thesis_fixes "
            "(id, project_id, document_id, issue_id, user_id, rule_id, fix_type, "
            "before, after, backup_path) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                fix_id, project_id, document_id, issue["id"], user_id,
                issue["rule_id"], fix_type,
                json.dumps(issue.get("evidence") or {}, ensure_ascii=False),
                json.dumps(result.get("verification") or {}, ensure_ascii=False),
                str(backup),
            ),
        ),
        (
            "UPDATE thesis_issues SET status = 'fixed', updated_at = now() "
            "WHERE id = %s AND user_id = %s",
            (issue["id"], user_id),
        ),
        (
            "UPDATE thesis_projects SET status = 'ready', updated_at = now() "
            "WHERE id = %s AND user_id = %s",
            (project_id, user_id),
        ),
    ])
    document = await get_document(user_id, document_id)
    if not document:
        raise RuntimeError("读取论文文档失败")
    return await _post_fix_result(user_id, project_id, issue["id"], fix_id, document)


async def undo_issue_fix(user_id: int, issue_id: str) -> dict[str, Any]:
    record = await _issue_with_document(user_id, issue_id)
    issue = record["issue"]
    fix_rows = await query(
        f"SELECT {FIX_COLUMNS}, f.backup_path FROM thesis_fixes f "
        "WHERE f.issue_id = %s AND f.user_id = %s AND f.undone_at IS NULL "
        "ORDER BY f.applied_at DESC LIMIT 1",
        (issue["id"], user_id),
    )
    if not fix_rows:
        raise ValueError("这条问题没有可撤销的修复记录")
    fix_row = fix_rows[0]
    fix = _fix_row(fix_row[:10])
    backup_path = fix_row[10]

    latest = await query(
        "SELECT id::text FROM thesis_fixes "
        "WHERE document_id = %s AND user_id = %s AND undone_at IS NULL "
        "ORDER BY applied_at DESC LIMIT 1",
        (issue["document_id"], user_id),
    )
    if not latest or latest[0][0] != fix["id"]:
        raise ValueError("只能按顺序撤销最近一次修复；请先撤销之后应用的修复")

    working = Path(record["working_path"] or "")
    backup = Path(backup_path or "")
    if not working.is_file() or not backup.is_file():
        raise ValueError("修复备份不存在，无法撤销")

    await asyncio.to_thread(shutil.copy2, backup, working)
    model = await asyncio.to_thread(parse_docx, working)
    sha256 = await asyncio.to_thread(file_sha256, working)
    project_id = issue["project_id"]
    document_id = issue["document_id"]
    await transaction([
        (
            "UPDATE thesis_documents SET working_sha256 = %s, "
            "version = GREATEST(version - 1, 1), document_model = %s, stats = %s, "
            "updated_at = now() WHERE id = %s AND user_id = %s",
            (
                sha256,
                json.dumps(model.to_dict(), ensure_ascii=False),
                json.dumps(model.stats, ensure_ascii=False),
                document_id, user_id,
            ),
        ),
        (
            "UPDATE thesis_fixes SET undone_at = now() WHERE id = %s AND user_id = %s",
            (fix["id"], user_id),
        ),
        (
            "UPDATE thesis_issues SET status = 'open', updated_at = now() "
            "WHERE id = %s AND user_id = %s",
            (issue["id"], user_id),
        ),
        (
            "UPDATE thesis_projects SET updated_at = now() "
            "WHERE id = %s AND user_id = %s",
            (project_id, user_id),
        ),
    ])
    document = await get_document(user_id, document_id)
    if not document:
        raise RuntimeError("读取论文文档失败")
    return await _post_fix_result(user_id, project_id, issue["id"], fix["id"], document)


async def get_citations(user_id: int, project_id: str) -> dict[str, Any] | None:
    project = await get_project(user_id, project_id)
    if not project:
        return None
    full = await _latest_document_full(user_id, project_id)
    document_id = full["document"]["id"] if full else ""
    rows = await query(
        f"SELECT {CITATION_COLUMNS} FROM thesis_citations c "
        "WHERE c.project_id = %s AND c.user_id = %s ORDER BY c.created_at, c.id",
        (project_id, user_id),
    )
    citations = [_citation_row(row) for row in rows]
    references: list[dict[str, Any]] = []
    for row in citations:
        if row["kind"] != "reference":
            continue
        entry = dict(row["normalized"])
        entry["citation_id"] = row["id"]
        entry["doi"] = row["doi"] or extract_doi(row["raw"]) or ""
        entry["metadata_status"] = row["metadata_status"] or ""
        entry["metadata"] = row["metadata"] or {}
        references.append(entry)
    in_text = [row["normalized"] for row in citations if row["kind"] == "in_text"]
    return {
        "project_id": project_id,
        "document_id": document_id,
        "references": references,
        "in_text": in_text,
        "citations": citations,
        "reference_section_found": bool(references),
        "generated_at": datetime.now(timezone.utc),
    }


async def audit_project_citations(user_id: int, project_id: str) -> dict[str, Any]:
    project = await get_project(user_id, project_id)
    if not project:
        raise LookupError("论文项目不存在")
    full = await _latest_document_full(user_id, project_id)
    if not full or not full["document_model"]:
        raise ValueError("请先导入一份可解析的 DOCX")
    model = DocumentModel.from_dict(full["document_model"])
    template = get_template(project["template_id"])
    audit = audit_citations(model, template)
    document_id = full["document"]["id"]
    await transaction(_citation_statements(user_id, project_id, document_id, audit))
    result = await get_citations(user_id, project_id)
    if result is None:
        raise RuntimeError("读取引用结果失败")
    return result


async def verify_citation_metadata(
    user_id: int,
    project_id: str,
    *,
    client: Any = None,
) -> dict[str, Any]:
    """Run L2 DOI metadata checks (Crossref).  Only DOIs leave the machine."""
    data = await get_citations(user_id, project_id)
    if data is None:
        raise LookupError("论文项目不存在")
    rows = [row for row in data["citations"] if row["kind"] == "reference"]
    if not rows:
        raise ValueError("没有参考文献；请先运行引用核对")

    now = datetime.now(timezone.utc)
    doi_rows: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        doi = extract_doi(row["raw"])
        if doi:
            doi_rows.setdefault(doi.lower(), []).append(row)

    outcomes: dict[str, dict[str, Any]] = {}
    stale: dict[str, tuple] = {}
    if doi_rows:
        cached = await query(
            "SELECT doi, status, metadata, fetched_at FROM thesis_metadata_cache "
            "WHERE doi = ANY(%s)",
            (sorted(doi_rows),),
        )
        for doi, status, metadata, fetched_at in cached:
            if cache_is_fresh(fetched_at, now=now):
                outcomes[doi] = {
                    "status": status,
                    "metadata": metadata or {},
                    "cached": True,
                    "fetched_at": fetched_at,
                }
            else:
                stale[doi] = (status, metadata, fetched_at)

    to_fetch = [doi for doi in doi_rows if doi not in outcomes]
    fetched = await fetch_dois(to_fetch, client=client) if to_fetch else {}
    cache_statements: list[tuple[str, tuple]] = []
    for doi, result in fetched.items():
        if result.get("ok"):
            metadata = result.get("metadata") or {}
            outcomes[doi] = {
                "status": "ok",
                "metadata": metadata,
                "cached": False,
                "fetched_at": now,
            }
            cache_statements.append((
                "INSERT INTO thesis_metadata_cache (doi, status, metadata, fetched_at) "
                "VALUES (%s, 'ok', %s, now()) ON CONFLICT (doi) DO UPDATE SET "
                "status = EXCLUDED.status, metadata = EXCLUDED.metadata, "
                "fetched_at = EXCLUDED.fetched_at",
                (doi, json.dumps(metadata, ensure_ascii=False)),
            ))
        elif result.get("status") == "not_found":
            outcomes[doi] = {
                "status": "not_found",
                "metadata": {},
                "cached": False,
                "fetched_at": now,
            }
            cache_statements.append((
                "INSERT INTO thesis_metadata_cache (doi, status, metadata, fetched_at) "
                "VALUES (%s, 'not_found', '{}'::jsonb, now()) "
                "ON CONFLICT (doi) DO UPDATE SET status = EXCLUDED.status, "
                "metadata = EXCLUDED.metadata, fetched_at = EXCLUDED.fetched_at",
                (doi,),
            ))
        else:
            error = str(result.get("error") or "联网核验失败")
            if doi in stale:
                _, stale_metadata, stale_at = stale[doi]
                outcomes[doi] = {
                    "status": "needs_review",
                    "metadata": stale_metadata or {},
                    "cached": True,
                    "fetched_at": stale_at,
                    "error": f"{error}；展示的是过期缓存，请人工确认",
                }
            else:
                outcomes[doi] = {
                    "status": "needs_review",
                    "metadata": {},
                    "cached": False,
                    "fetched_at": now,
                    "error": error,
                }

    statements = list(cache_statements)
    for row in rows:
        doi = extract_doi(row["raw"])
        if not doi:
            classification = {
                "status": "no_doi",
                "detail": "条目中没有 DOI，未联网核验",
                "doi": None,
                "metadata": {},
            }
            outcome: dict[str, Any] = {}
            fetched_at = None
        else:
            outcome = outcomes.get(doi.lower(), {})
            if outcome.get("status") == "needs_review":
                classification = classify_reference(
                    row["raw"],
                    outcome.get("metadata") or None,
                    error=str(outcome.get("error") or "联网核验失败"),
                )
            else:
                classification = classify_reference(
                    row["raw"], outcome.get("metadata") or None
                )
            fetched_at = outcome.get("fetched_at") or now
        metadata_payload = {
            **(classification.get("metadata") or {}),
            "detail": classification.get("detail") or "",
            "source": "crossref" if doi else "none",
            "cached": bool(outcome.get("cached")) if doi else False,
            "checked_at": now.isoformat(),
        }
        statements.append((
            "UPDATE thesis_citations SET doi = %s, metadata_status = %s, "
            "metadata = %s, metadata_fetched_at = %s "
            "WHERE id = %s AND user_id = %s",
            (
                (doi or "").lower(),
                classification["status"],
                json.dumps(metadata_payload, ensure_ascii=False),
                fetched_at,
                row["id"],
                user_id,
            ),
        ))

    await transaction(statements)
    result = await get_citations(user_id, project_id)
    if result is None:
        raise RuntimeError("读取引用结果失败")
    return result


async def list_reference_pdfs(user_id: int, project_id: str) -> list[dict[str, Any]]:
    project_id = _valid_uuid(project_id)
    rows = await query(
        f"SELECT {REFERENCE_PDF_COLUMNS} FROM thesis_reference_pdfs r "
        "WHERE r.project_id = %s AND r.user_id = %s ORDER BY r.created_at",
        (project_id, user_id),
    )
    return [_reference_pdf_row(row) for row in rows]


async def import_reference_pdf(
    user_id: int,
    project_id: str,
    upload: UploadFile,
) -> dict[str, Any]:
    project_id = _valid_uuid(project_id)
    project = await get_project(user_id, project_id)
    if not project:
        raise LookupError("论文项目不存在")
    count = await query(
        "SELECT count(*) FROM thesis_reference_pdfs WHERE project_id = %s AND user_id = %s",
        (project_id, user_id),
    )
    if int(count[0][0] or 0) >= 20:
        raise ValueError("每个项目最多附加 20 个参考文献 PDF")

    filename = sanitize_filename(upload.filename or "reference.pdf")
    if not filename.lower().endswith(".pdf"):
        raise ValueError("只支持 .pdf 文件")

    dest_dir = thesis_container(user_id, project_id) / "references"
    await asyncio.to_thread(lambda: dest_dir.mkdir(parents=True, exist_ok=True))
    pdf_id = str(uuid.uuid4())
    final_path = dest_dir / f"{pdf_id}.pdf"
    tmp_path = dest_dir / f".{pdf_id}.uploading"
    max_bytes = settings.attachment_max_mb * 1024 * 1024
    total = 0
    digest = hashlib.sha256()

    try:
        with open(tmp_path, "wb") as out:
            while chunk := await upload.read(1024 * 1024):
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError(f"文件超过上限（{settings.attachment_max_mb}MB）")
                digest.update(chunk)
                out.write(chunk)
        if total == 0:
            raise ValueError("文件为空")
        with open(tmp_path, "rb") as probe:
            if probe.read(5) != b"%PDF-":
                raise ValueError("不是有效的 PDF 文件")
        pages = await asyncio.to_thread(extract_pdf_pages, tmp_path)
        tmp_path.replace(final_path)
        page_count = len(pages)
        await execute(
            "INSERT INTO thesis_reference_pdfs "
            "(id, project_id, user_id, filename, sha256, size, page_count, storage_path) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (
                pdf_id, project_id, user_id, filename, digest.hexdigest(),
                total, page_count, str(final_path),
            ),
        )
    except Exception:
        tmp_path.unlink(missing_ok=True)
        final_path.unlink(missing_ok=True)
        raise

    rows = await query(
        f"SELECT {REFERENCE_PDF_COLUMNS} FROM thesis_reference_pdfs r "
        "WHERE r.id = %s AND r.user_id = %s",
        (pdf_id, user_id),
    )
    if not rows:
        raise RuntimeError("保存参考文献 PDF 失败")
    return _reference_pdf_row(rows[0])


async def delete_reference_pdf(user_id: int, pdf_id: str) -> bool:
    try:
        pdf_id = _valid_uuid(pdf_id)
    except LookupError:
        return False
    rows = await query(
        "SELECT storage_path FROM thesis_reference_pdfs WHERE id = %s AND user_id = %s",
        (pdf_id, user_id),
    )
    if not rows:
        return False
    await execute(
        "DELETE FROM thesis_reference_pdfs WHERE id = %s AND user_id = %s",
        (pdf_id, user_id),
    )
    await asyncio.to_thread(
        lambda: Path(rows[0][0]).unlink(missing_ok=True)
    )
    return True


async def list_citation_evidence(
    user_id: int,
    project_id: str,
) -> list[dict[str, Any]]:
    project_id = _valid_uuid(project_id)
    rows = await query(
        f"SELECT {EVIDENCE_COLUMNS} FROM thesis_citation_evidence e "
        "LEFT JOIN thesis_reference_pdfs r ON r.id = e.pdf_id "
        "WHERE e.project_id = %s AND e.user_id = %s ORDER BY e.created_at, e.id",
        (project_id, user_id),
    )
    return [_evidence_row(row) for row in rows]


async def locate_citation_evidence(user_id: int, project_id: str) -> dict[str, Any]:
    """L3: locate candidate quotes in attached PDFs.  No support judgement."""
    project_id = _valid_uuid(project_id)
    project = await get_project(user_id, project_id)
    if not project:
        raise LookupError("论文项目不存在")
    full = await _latest_document_full(user_id, project_id)
    document_id = full["document"]["id"] if full else None
    citations = await get_citations(user_id, project_id)
    if citations is None:
        raise LookupError("论文项目不存在")
    references = list(citations["references"])
    if not references:
        raise ValueError("没有参考文献；请先运行引用核对")

    pdfs = await list_reference_pdfs(user_id, project_id)
    if not pdfs:
        raise ValueError("请先附加至少一个参考文献 PDF")

    loaded: list[dict[str, Any]] = []
    for pdf in pdfs:
        rows = await query(
            "SELECT storage_path FROM thesis_reference_pdfs WHERE id = %s",
            (pdf["id"],),
        )
        path = Path(rows[0][0]) if rows else None
        if path is None or not path.exists():
            continue
        try:
            pages = await asyncio.to_thread(extract_pdf_pages, path)
        except ValueError as exc:
            raise ValueError(f"{pdf['filename']}：{exc}") from exc
        loaded.append({**pdf, "pages": pages})

    if not loaded:
        raise ValueError("没有可读取的 PDF 文件，请重新上传")
    matches = locate_references(references, loaded)
    existing = await query(
        "SELECT id, reference_index, pdf_id::text, page, support, note "
        "FROM thesis_citation_evidence WHERE project_id = %s AND user_id = %s",
        (project_id, user_id),
    )
    existing_by_key = {
        (row[1], str(row[2]) if row[2] else "", row[3]): {
            "id": str(row[0]),
            "support": row[4] or "needs_review",
            "note": row[5] or "",
        }
        for row in existing
    }
    matched_ids: set[str] = set()
    statements: list[tuple[str, tuple]] = []
    for match in matches:
        key = (match.get("reference_index"), str(match.get("pdf_id") or ""), match.get("page"))
        prior = existing_by_key.get(key)
        if prior:
            matched_ids.add(prior["id"])
            statements.append((
                "UPDATE thesis_citation_evidence SET quote = %s, score = %s, "
                "method = %s, reference_raw = %s, updated_at = now() "
                "WHERE id = %s AND user_id = %s",
                (
                    match["quote"], match["score"], match["method"],
                    match["reference_raw"][:500], prior["id"], user_id,
                ),
            ))
        else:
            evidence_id = str(uuid.uuid4())
            matched_ids.add(evidence_id)
            statements.append((
                "INSERT INTO thesis_citation_evidence "
                "(id, project_id, document_id, user_id, reference_index, "
                "reference_raw, pdf_id, page, quote, score, method) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    evidence_id, project_id, document_id, user_id,
                    match.get("reference_index"), match["reference_raw"][:500],
                    match.get("pdf_id"), match.get("page"), match["quote"],
                    match["score"], match["method"],
                ),
            ))
    stale_ids = [
        uuid.UUID(row["id"])
        for row in existing_by_key.values()
        if row["id"] not in matched_ids
    ]
    if stale_ids:
        statements.append((
            "DELETE FROM thesis_citation_evidence WHERE id = ANY(%s) AND user_id = %s",
            (stale_ids, user_id),
        ))
    if statements:
        await transaction(statements)

    evidence = await list_citation_evidence(user_id, project_id)
    return {
        "project_id": project_id,
        "document_id": document_id or "",
        "pdfs": pdfs,
        "evidence": evidence,
        "matched": len(matches),
        "total_references": len(references),
        "located_at": datetime.now(timezone.utc),
    }


async def update_citation_evidence(
    user_id: int,
    evidence_id: str,
    *,
    support: str,
    note: str | None = None,
) -> dict[str, Any] | None:
    if support not in EVIDENCE_SUPPORT:
        raise ValueError("不支持的支持度取值")
    try:
        evidence_id = _valid_uuid(evidence_id)
    except LookupError:
        return None
    rows = await execute(
        "UPDATE thesis_citation_evidence SET support = %s, "
        "note = COALESCE(%s, note), updated_at = now() "
        "WHERE id = %s AND user_id = %s RETURNING id",
        (support, note, evidence_id, user_id),
    )
    if not rows:
        return None
    rows = await query(
        f"SELECT {EVIDENCE_COLUMNS} FROM thesis_citation_evidence e "
        "LEFT JOIN thesis_reference_pdfs r ON r.id = e.pdf_id "
        "WHERE e.id = %s AND e.user_id = %s",
        (evidence_id, user_id),
    )
    return _evidence_row(rows[0]) if rows else None


async def list_disclosures(user_id: int, project_id: str) -> list[dict[str, Any]]:
    project_id = _valid_uuid(project_id)
    rows = await query(
        f"SELECT {DISCLOSURE_COLUMNS} FROM thesis_disclosures d "
        "WHERE d.project_id = %s AND d.user_id = %s ORDER BY d.created_at",
        (project_id, user_id),
    )
    return [_disclosure_row(row) for row in rows]


async def create_disclosure(
    user_id: int,
    project_id: str,
    *,
    tool: str,
    tool_version: str,
    purpose: str,
    stage: str,
    prompt: str,
    output: str,
    modified: bool,
) -> dict[str, Any] | None:
    project = await get_project(user_id, project_id)
    if not project:
        return None
    disclosure_id = str(uuid.uuid4())
    await execute(
        "INSERT INTO thesis_disclosures "
        "(id, project_id, user_id, tool, tool_version, purpose, stage, prompt, output, modified) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            disclosure_id, project_id, user_id, tool.strip(), tool_version.strip(),
            purpose.strip(), stage.strip(), prompt.strip(), output.strip(), modified,
        ),
    )
    rows = await query(
        f"SELECT {DISCLOSURE_COLUMNS} FROM thesis_disclosures d "
        "WHERE d.id = %s AND d.user_id = %s",
        (disclosure_id, user_id),
    )
    return _disclosure_row(rows[0]) if rows else None


async def delete_disclosure(user_id: int, disclosure_id: str) -> bool:
    disclosure_id = _valid_uuid(disclosure_id)
    rows = await execute(
        "DELETE FROM thesis_disclosures WHERE id = %s AND user_id = %s RETURNING id",
        (disclosure_id, user_id),
    )
    return bool(rows)


async def build_report(user_id: int, project_id: str) -> dict[str, Any] | None:
    project = await get_project(user_id, project_id)
    if not project:
        return None
    documents = await list_documents(user_id, project_id)
    issues = await list_issues(user_id, project_id)
    fixes = await list_fixes(user_id, project_id)
    by_category: dict[str, int] = {}
    for issue in issues:
        category = str(issue.get("category") or "other")
        by_category[category] = by_category.get(category, 0) + 1
    template = get_template(project["template_id"])
    return {
        "project": project,
        "document": documents[0] if documents else None,
        "template": _template_public(template),
        "counts": _counts(issues),
        "by_category": by_category,
        "issues": issues,
        "fixes": fixes,
        "generated_at": datetime.now(timezone.utc),
    }


def _enrich_citation_audit(
    audit: dict[str, Any],
    persisted: dict[str, Any] | None,
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    references = audit.setdefault("references", [])
    if persisted:
        stored = {
            str(row.get("raw") or ""): row
            for row in persisted.get("citations") or []
            if row.get("kind") == "reference"
        }
        for item in references:
            match = stored.get(str(item.get("raw") or ""))
            if match:
                item["doi"] = match.get("doi") or ""
                item["metadata_status"] = match.get("metadata_status") or ""
                item["metadata"] = match.get("metadata") or {}
    by_index: dict[Any, dict[str, Any]] = {}
    by_raw: dict[str, dict[str, Any]] = {}
    for item in evidence:
        if item.get("reference_index") is not None:
            by_index.setdefault(item["reference_index"], item)
        by_raw.setdefault(str(item.get("reference_raw") or ""), item)
    for item in references:
        match = by_index.get(item.get("index")) or by_raw.get(
            str(item.get("raw") or "")
        )
        if match:
            item["evidence_page"] = match.get("page")
            item["evidence_support"] = match.get("support")
            item["evidence_quote"] = match.get("quote")
            item["evidence_pdf"] = match.get("pdf_filename")
    return audit


async def export_project(user_id: int, project_id: str) -> tuple[Path, str] | None:
    project = await get_project(user_id, project_id)
    if not project:
        return None
    full = await _latest_document_full(user_id, project_id)
    if not full:
        raise ValueError("请先导入一份可解析的 DOCX")
    document = full["document"]
    template = get_template(project["template_id"])
    model = (
        DocumentModel.from_dict(full["document_model"])
        if full["document_model"]
        else None
    )
    audit = audit_citations(model, template) if model else {"references": [], "in_text": []}
    persisted = await get_citations(user_id, project_id)
    evidence = await list_citation_evidence(user_id, project_id)
    audit = _enrich_citation_audit(audit, persisted, evidence)
    issues = await list_issues(user_id, project_id, status="all")
    fixes = await list_fixes(user_id, project_id)
    disclosures = await list_disclosures(user_id, project_id)
    report = {
        "project": project,
        "document": document,
        "template": _template_public(template),
        "counts": _counts(issues),
        "by_category": {},
        "issues": issues,
        "fixes": fixes,
        "generated_at": datetime.now(timezone.utc),
    }
    report_html = render_report_html(report, audit, disclosures, fixes)
    report_docx = build_report_docx(report, audit, disclosures, fixes)
    disclosure_docx = build_disclosure_docx(project, template, disclosures)
    csv_text = citations_csv(audit)
    fixed_docx = Path(full["working_path"]) if full["working_path"] else None
    if fixed_docx is not None and not fixed_docx.is_file():
        fixed_docx = None
    export_dir = thesis_container(user_id, project_id) / "exports"
    zip_path = await asyncio.to_thread(
        write_export_package,
        export_dir,
        project["title"] or document["filename"],
        fixed_docx=fixed_docx,
        report_html=report_html,
        report_docx=report_docx,
        disclosure_docx=disclosure_docx,
        citations_csv_text=csv_text,
        fixes=fixes,
        project=project,
        template=_template_public(template),
        document=document,
    )
    return zip_path, zip_path.name


async def export_report_file(
    user_id: int,
    project_id: str,
    fmt: str,
) -> tuple[bytes, str, str] | None:
    """Return ``(content, filename, media_type)`` for the HTML/DOCX report."""
    project = await get_project(user_id, project_id)
    if not project:
        return None
    full = await _latest_document_full(user_id, project_id)
    if not full:
        raise ValueError("请先导入一份可解析的 DOCX")
    document = full["document"]
    template = get_template(project["template_id"])
    model = (
        DocumentModel.from_dict(full["document_model"])
        if full["document_model"]
        else None
    )
    audit = audit_citations(model, template) if model else {"references": [], "in_text": []}
    persisted = await get_citations(user_id, project_id)
    evidence = await list_citation_evidence(user_id, project_id)
    audit = _enrich_citation_audit(audit, persisted, evidence)
    issues = await list_issues(user_id, project_id, status="all")
    fixes = await list_fixes(user_id, project_id)
    disclosures = await list_disclosures(user_id, project_id)
    report = {
        "project": project,
        "document": document,
        "template": _template_public(template),
        "counts": _counts(issues),
        "by_category": {},
        "issues": issues,
        "fixes": fixes,
        "generated_at": datetime.now(timezone.utc),
    }
    base = sanitize_filename(project["title"] or "论文体检报告").removesuffix(".docx")
    if fmt == "docx":
        return (
            build_report_docx(report, audit, disclosures, fixes),
            f"{base}_体检报告.docx",
            DOCX_MIME,
        )
    html_text = render_report_html(report, audit, disclosures, fixes)
    return html_text.encode("utf-8"), f"{base}_体检报告.html", "text/html; charset=utf-8"

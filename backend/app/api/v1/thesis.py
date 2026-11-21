"""Thesis-mode endpoints: projects, DOCX import, scans and reports."""
from __future__ import annotations

import asyncio
from typing import NoReturn
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from starlette.background import BackgroundTask

from app.config import settings
from app.core.security.audit import AuditAction, log_audit
from app.core.security.auth import get_current_user
from app.core.security.limits import check_job_quota, ensure_token_budget
from app.core.storage.user_storage import storage_limit_bytes
from app.core.thesis import service, stage_service
from app.core.thesis.rules.builtin import list_templates
from app.core.thesis.stages import STAGE_LABELS
from app.models.schemas import (
    OkOut,
    ThesisApplyOut,
    ThesisCitationAuditOut,
    ThesisCitationEvidenceOut,
    ThesisCitationEvidenceUpdate,
    ThesisDisclosureCreate,
    ThesisDisclosureOut,
    ThesisDocumentDetailOut,
    ThesisDocumentOut,
    ThesisEvidenceLocateOut,
    ThesisFixOut,
    ThesisFixPreviewOut,
    ThesisIssueOut,
    ThesisIssueUpdate,
    ThesisProjectCreate,
    ThesisProjectDetailOut,
    ThesisProjectOut,
    ThesisProjectUpdate,
    ThesisReferencePdfOut,
    ThesisReportOut,
    ThesisScanOut,
    ThesisStageAdvanceIn,
    ThesisStageConfirmIn,
    ThesisStageContentIn,
    ThesisStageDraftIn,
    ThesisStageDraftOut,
    ThesisStageReadinessIn,
    ThesisStageReturnIn,
    ThesisStagesOut,
    ThesisTemplateOut,
)

router = APIRouter()

STAGE_DRAFT_PROMPT = """你在辅助作者推进学位论文的当前阶段。只输出这一阶段可以直接编辑的草稿，不写整篇论文。
规则：
1. 只处理当前阶段，不要提前写后续阶段的正文。
2. 不编造文献、数据、实验结果、学校要求或导师意见；缺少的信息写成「待补充」。
3. 不替作者下最终结论；需要作者决定的地方列出选项或问题。
4. 用简洁的 Markdown，小标题和列表为主，避免套话和重复。
5. 作者给了要求就以要求为准；没有要求就按阶段常规产出，并标出需要确认的点。
6. 不要声称已经核实、已经通过或已经完成。"""


def _clean_draft(text: str) -> str:
    value = (text or "").strip()
    if value.startswith("```"):
        lines = value.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        value = "\n".join(lines).strip()
    return value


def _raise_http(exc: Exception) -> NoReturn:
    if isinstance(exc, LookupError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    raise exc


def require_thesis_access(user: dict = Depends(get_current_user)) -> dict:
    """Mode-level gate shared by every thesis route.

    The deployment switch lets a server admin disable the whole mode; guests
    are refused by default because thesis files are long-lived and personal.
    """
    if not settings.thesis_server_enabled:
        raise HTTPException(status_code=403, detail="论文模式在当前部署中已关闭")
    if user.get("is_guest") and not settings.thesis_guest_enabled:
        raise HTTPException(
            status_code=403,
            detail="访客账号不能使用论文模式，请注册正式账号",
        )
    return user


@router.get("/thesis/templates", response_model=list[ThesisTemplateOut])
async def get_thesis_templates(user: dict = Depends(require_thesis_access)):
    return list_templates()


@router.get("/thesis/projects", response_model=list[ThesisProjectOut])
async def get_thesis_projects(user: dict = Depends(require_thesis_access)):
    return await service.list_projects(user["id"])


@router.post("/thesis/projects", response_model=ThesisProjectOut, status_code=201)
async def create_thesis_project(
    body: ThesisProjectCreate,
    user: dict = Depends(require_thesis_access),
):
    try:
        project = await service.create_project(
            user["id"],
            title=body.title,
            school=body.school,
            degree=body.degree,
            template_id=body.template_id,
            source_repo_id=body.source_repo_id,
            source_notes=body.source_notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await log_audit(
        AuditAction.THESIS_PROJECT_CREATE,
        user_id=str(user["id"]),
        details={"project_id": project["id"], "title": project["title"]},
    )
    return project


@router.get("/thesis/projects/{project_id}", response_model=ThesisProjectDetailOut)
async def get_thesis_project(
    project_id: str,
    user: dict = Depends(require_thesis_access),
):
    project = await service.get_project(user["id"], project_id)
    if not project:
        raise HTTPException(status_code=404, detail="论文项目不存在")
    documents = await service.list_documents(user["id"], project_id)
    return {**project, "documents": documents}


@router.patch("/thesis/projects/{project_id}", response_model=ThesisProjectOut)
async def update_thesis_project(
    project_id: str,
    body: ThesisProjectUpdate,
    user: dict = Depends(require_thesis_access),
):
    provided = body.model_fields_set
    before = await service.get_project(user["id"], project_id)
    if not before:
        raise HTTPException(status_code=404, detail="论文项目不存在")
    try:
        project = await service.update_project(
            user["id"],
            project_id,
            title=body.title,
            school=body.school,
            degree=body.degree,
            template_id=body.template_id,
            source_repo_id=body.source_repo_id if "source_repo_id" in provided else None,
            source_notes=body.source_notes if "source_notes" in provided else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not project:
        raise HTTPException(status_code=404, detail="论文项目不存在")
    await log_audit(
        AuditAction.THESIS_PROJECT_UPDATE,
        user_id=str(user["id"]),
        details={
            "project_id": project_id,
            "before": {
                "title": before.get("title"),
                "template_id": before.get("template_id"),
                "source_repo_id": before.get("source_repo_id"),
            },
            "after": {
                "title": project.get("title"),
                "template_id": project.get("template_id"),
                "source_repo_id": project.get("source_repo_id"),
            },
            "fields": sorted(provided),
        },
        risk_level="warn" if "template_id" in provided or "source_repo_id" in provided else "safe",
    )
    return project


@router.delete("/thesis/projects/{project_id}", response_model=OkOut)
async def delete_thesis_project(
    project_id: str,
    user: dict = Depends(require_thesis_access),
):
    if not await service.delete_project(user["id"], project_id):
        raise HTTPException(status_code=404, detail="论文项目不存在")
    await log_audit(
        AuditAction.THESIS_PROJECT_DELETE,
        user_id=str(user["id"]),
        details={"project_id": project_id},
    )
    return {"ok": True}


@router.get(
    "/thesis/projects/{project_id}/documents",
    response_model=list[ThesisDocumentOut],
)
async def get_thesis_documents(
    project_id: str,
    user: dict = Depends(require_thesis_access),
):
    project = await service.get_project(user["id"], project_id)
    if not project:
        raise HTTPException(status_code=404, detail="论文项目不存在")
    return await service.list_documents(user["id"], project_id)


@router.post(
    "/thesis/projects/{project_id}/documents",
    response_model=ThesisDocumentOut,
    status_code=201,
)
async def upload_thesis_document(
    project_id: str,
    file: UploadFile = File(...),
    user: dict = Depends(require_thesis_access),
):
    check_job_quota(user, "thesis_import")
    try:
        document = await service.import_document(
            user["id"], project_id, file,
            max_storage_bytes=storage_limit_bytes(user),
        )
    except Exception as exc:  # noqa: BLE001 - map service errors to HTTP
        _raise_http(exc)
    await log_audit(
        AuditAction.THESIS_DOCUMENT_IMPORT,
        user_id=str(user["id"]),
        details={
            "project_id": project_id,
            "document_id": document["id"],
            "filename": document["filename"],
            "sha256": document["sha256"],
            "status": document["status"],
        },
    )
    return document


@router.get(
    "/thesis/documents/{document_id}",
    response_model=ThesisDocumentDetailOut,
)
async def get_thesis_document(
    document_id: str,
    user: dict = Depends(require_thesis_access),
):
    document = await service.get_document(user["id"], document_id, include_model=True)
    if not document:
        raise HTTPException(status_code=404, detail="论文文档不存在")
    return document


@router.post(
    "/thesis/projects/{project_id}/scan",
    response_model=ThesisScanOut,
)
async def scan_thesis_project(
    project_id: str,
    template_id: str | None = Query(default=None, max_length=80),
    user: dict = Depends(require_thesis_access),
):
    check_job_quota(user, "thesis_scan")
    try:
        result = await service.scan_project(user["id"], project_id, template_id=template_id)
    except Exception as exc:  # noqa: BLE001 - map service errors to HTTP
        _raise_http(exc)
    await log_audit(
        AuditAction.THESIS_SCAN,
        user_id=str(user["id"]),
        details={
            "project_id": project_id,
            "document_id": result["document_id"],
            "template_id": result["template_id"],
            "counts": result["counts"],
        },
    )
    return result


@router.get(
    "/thesis/projects/{project_id}/issues",
    response_model=list[ThesisIssueOut],
)
async def get_thesis_issues(
    project_id: str,
    status: str = Query(default="open", pattern="^(open|ignored|fixed|all)$"),
    user: dict = Depends(require_thesis_access),
):
    project = await service.get_project(user["id"], project_id)
    if not project:
        raise HTTPException(status_code=404, detail="论文项目不存在")
    return await service.list_issues(user["id"], project_id, status=status)


@router.get(
    "/thesis/projects/{project_id}/report",
    response_model=ThesisReportOut,
)
async def get_thesis_report(
    project_id: str,
    user: dict = Depends(require_thesis_access),
):
    report = await service.build_report(user["id"], project_id)
    if not report:
        raise HTTPException(status_code=404, detail="论文项目不存在")
    return report


@router.patch("/thesis/issues/{issue_id}", response_model=ThesisIssueOut)
async def update_thesis_issue(
    issue_id: str,
    body: ThesisIssueUpdate,
    user: dict = Depends(require_thesis_access),
):
    try:
        issue = await service.set_issue_status(user["id"], issue_id, body.status)
    except Exception as exc:  # noqa: BLE001 - map service errors to HTTP
        _raise_http(exc)
    if not issue:
        raise HTTPException(status_code=404, detail="论文问题不存在")
    await log_audit(
        AuditAction.THESIS_ISSUE_UPDATE,
        user_id=str(user["id"]),
        details={"issue_id": issue_id, "status": body.status},
    )
    return issue


@router.post(
    "/thesis/issues/{issue_id}/preview",
    response_model=ThesisFixPreviewOut,
)
async def preview_thesis_fix(
    issue_id: str,
    user: dict = Depends(require_thesis_access),
):
    try:
        preview = await service.preview_issue_fix(user["id"], issue_id)
    except Exception as exc:  # noqa: BLE001 - map service errors to HTTP
        _raise_http(exc)
    return preview


@router.post("/thesis/issues/{issue_id}/apply", response_model=ThesisApplyOut)
async def apply_thesis_fix(
    issue_id: str,
    user: dict = Depends(require_thesis_access),
):
    try:
        result = await service.apply_issue_fix(user["id"], issue_id)
    except Exception as exc:  # noqa: BLE001 - map service errors to HTTP
        _raise_http(exc)
    await log_audit(
        AuditAction.THESIS_FIX_APPLY,
        user_id=str(user["id"]),
        details={
            "issue_id": issue_id,
            "fix_id": result["fix"]["id"] if result.get("fix") else None,
            "rule_id": result["issue"]["rule_id"] if result.get("issue") else None,
        },
    )
    return result


@router.post("/thesis/issues/{issue_id}/undo", response_model=ThesisApplyOut)
async def undo_thesis_fix(
    issue_id: str,
    user: dict = Depends(require_thesis_access),
):
    try:
        result = await service.undo_issue_fix(user["id"], issue_id)
    except Exception as exc:  # noqa: BLE001 - map service errors to HTTP
        _raise_http(exc)
    await log_audit(
        AuditAction.THESIS_FIX_UNDO,
        user_id=str(user["id"]),
        details={"issue_id": issue_id},
    )
    return result


@router.get(
    "/thesis/projects/{project_id}/fixes",
    response_model=list[ThesisFixOut],
)
async def get_thesis_fixes(
    project_id: str,
    user: dict = Depends(require_thesis_access),
):
    project = await service.get_project(user["id"], project_id)
    if not project:
        raise HTTPException(status_code=404, detail="论文项目不存在")
    return await service.list_fixes(user["id"], project_id)


@router.get(
    "/thesis/projects/{project_id}/citations",
    response_model=ThesisCitationAuditOut,
)
async def get_thesis_citations(
    project_id: str,
    user: dict = Depends(require_thesis_access),
):
    result = await service.get_citations(user["id"], project_id)
    if not result:
        raise HTTPException(status_code=404, detail="论文项目不存在")
    return result


@router.post(
    "/thesis/projects/{project_id}/citations/audit",
    response_model=ThesisCitationAuditOut,
)
async def audit_thesis_citations(
    project_id: str,
    user: dict = Depends(require_thesis_access),
):
    check_job_quota(user, "thesis_citation_audit")
    try:
        result = await service.audit_project_citations(user["id"], project_id)
    except Exception as exc:  # noqa: BLE001 - map service errors to HTTP
        _raise_http(exc)
    await log_audit(
        AuditAction.THESIS_CITATION_AUDIT,
        user_id=str(user["id"]),
        details={
            "project_id": project_id,
            "references": len(result.get("references") or []),
            "in_text": len(result.get("in_text") or []),
        },
    )
    return result


@router.post(
    "/thesis/projects/{project_id}/citations/metadata",
    response_model=ThesisCitationAuditOut,
)
async def verify_thesis_citation_metadata(
    project_id: str,
    user: dict = Depends(require_thesis_access),
):
    check_job_quota(user, "thesis_citation_metadata")
    try:
        result = await service.verify_citation_metadata(user["id"], project_id)
    except Exception as exc:  # noqa: BLE001 - map service errors to HTTP
        _raise_http(exc)
    references = result.get("references") or []
    await log_audit(
        AuditAction.THESIS_CITATION_METADATA,
        user_id=str(user["id"]),
        details={
            "project_id": project_id,
            "references": len(references),
            "verified": sum(
                1 for item in references if item.get("metadata_status") == "verified"
            ),
        },
    )
    return result


@router.get(
    "/thesis/projects/{project_id}/reference-pdfs",
    response_model=list[ThesisReferencePdfOut],
)
async def get_thesis_reference_pdfs(
    project_id: str,
    user: dict = Depends(require_thesis_access),
):
    project = await service.get_project(user["id"], project_id)
    if not project:
        raise HTTPException(status_code=404, detail="论文项目不存在")
    return await service.list_reference_pdfs(user["id"], project_id)


@router.post(
    "/thesis/projects/{project_id}/reference-pdfs",
    response_model=ThesisReferencePdfOut,
    status_code=201,
)
async def upload_thesis_reference_pdf(
    project_id: str,
    file: UploadFile = File(...),
    user: dict = Depends(require_thesis_access),
):
    check_job_quota(user, "thesis_reference_pdf")
    try:
        pdf = await service.import_reference_pdf(
            user["id"], project_id, file,
            max_storage_bytes=storage_limit_bytes(user),
        )
    except Exception as exc:  # noqa: BLE001 - map service errors to HTTP
        _raise_http(exc)
    await log_audit(
        AuditAction.THESIS_REFERENCE_PDF_IMPORT,
        user_id=str(user["id"]),
        details={
            "project_id": project_id,
            "pdf_id": pdf["id"],
            "filename": pdf["filename"],
            "page_count": pdf["page_count"],
        },
    )
    return pdf


@router.delete("/thesis/reference-pdfs/{pdf_id}", response_model=OkOut)
async def delete_thesis_reference_pdf(
    pdf_id: str,
    user: dict = Depends(require_thesis_access),
):
    if not await service.delete_reference_pdf(user["id"], pdf_id):
        raise HTTPException(status_code=404, detail="参考文献 PDF 不存在")
    await log_audit(
        AuditAction.THESIS_REFERENCE_PDF_DELETE,
        user_id=str(user["id"]),
        details={"pdf_id": pdf_id},
    )
    return {"ok": True}


@router.get(
    "/thesis/projects/{project_id}/citations/evidence",
    response_model=list[ThesisCitationEvidenceOut],
)
async def get_thesis_citation_evidence(
    project_id: str,
    user: dict = Depends(require_thesis_access),
):
    project = await service.get_project(user["id"], project_id)
    if not project:
        raise HTTPException(status_code=404, detail="论文项目不存在")
    return await service.list_citation_evidence(user["id"], project_id)


@router.post(
    "/thesis/projects/{project_id}/citations/locate",
    response_model=ThesisEvidenceLocateOut,
)
async def locate_thesis_citation_evidence(
    project_id: str,
    user: dict = Depends(require_thesis_access),
):
    check_job_quota(user, "thesis_citation_locate")
    try:
        result = await service.locate_citation_evidence(user["id"], project_id)
    except Exception as exc:  # noqa: BLE001 - map service errors to HTTP
        _raise_http(exc)
    await log_audit(
        AuditAction.THESIS_CITATION_EVIDENCE_LOCATE,
        user_id=str(user["id"]),
        details={
            "project_id": project_id,
            "matched": result["matched"],
            "references": result["total_references"],
        },
    )
    return result


@router.patch(
    "/thesis/citations/evidence/{evidence_id}",
    response_model=ThesisCitationEvidenceOut,
)
async def update_thesis_citation_evidence(
    evidence_id: str,
    body: ThesisCitationEvidenceUpdate,
    user: dict = Depends(require_thesis_access),
):
    try:
        evidence = await service.update_citation_evidence(
            user["id"],
            evidence_id,
            support=body.support,
            note=body.note,
        )
    except Exception as exc:  # noqa: BLE001 - map service errors to HTTP
        _raise_http(exc)
    if not evidence:
        raise HTTPException(status_code=404, detail="引用证据不存在")
    await log_audit(
        AuditAction.THESIS_CITATION_EVIDENCE_UPDATE,
        user_id=str(user["id"]),
        details={"evidence_id": evidence_id, "support": body.support},
    )
    return evidence


@router.get(
    "/thesis/projects/{project_id}/disclosures",
    response_model=list[ThesisDisclosureOut],
)
async def get_thesis_disclosures(
    project_id: str,
    user: dict = Depends(require_thesis_access),
):
    project = await service.get_project(user["id"], project_id)
    if not project:
        raise HTTPException(status_code=404, detail="论文项目不存在")
    return await service.list_disclosures(user["id"], project_id)


@router.post(
    "/thesis/projects/{project_id}/disclosures",
    response_model=ThesisDisclosureOut,
    status_code=201,
)
async def create_thesis_disclosure(
    project_id: str,
    body: ThesisDisclosureCreate,
    user: dict = Depends(require_thesis_access),
):
    disclosure = await service.create_disclosure(
        user["id"],
        project_id,
        tool=body.tool,
        tool_version=body.tool_version,
        purpose=body.purpose,
        stage=body.stage,
        prompt=body.prompt,
        output=body.output,
        modified=body.modified,
    )
    if not disclosure:
        raise HTTPException(status_code=404, detail="论文项目不存在")
    await log_audit(
        AuditAction.THESIS_DISCLOSURE_CREATE,
        user_id=str(user["id"]),
        details={"project_id": project_id, "disclosure_id": disclosure["id"]},
    )
    return disclosure


@router.delete("/thesis/disclosures/{disclosure_id}", response_model=OkOut)
async def delete_thesis_disclosure(
    disclosure_id: str,
    user: dict = Depends(require_thesis_access),
):
    try:
        deleted = await service.delete_disclosure(user["id"], disclosure_id)
    except Exception as exc:  # noqa: BLE001 - map service errors to HTTP
        _raise_http(exc)
    if not deleted:
        raise HTTPException(status_code=404, detail="AI 使用记录不存在")
    await log_audit(
        AuditAction.THESIS_DISCLOSURE_DELETE,
        user_id=str(user["id"]),
        details={"disclosure_id": disclosure_id},
    )
    return {"ok": True}


@router.get("/thesis/projects/{project_id}/report/export")
async def export_thesis_report(
    project_id: str,
    fmt: str = Query(default="html", alias="format", pattern="^(html|docx)$"),
    user: dict = Depends(require_thesis_access),
):
    try:
        result = await service.export_report_file(user["id"], project_id, fmt)
    except Exception as exc:  # noqa: BLE001 - map service errors to HTTP
        _raise_http(exc)
    if result is None:
        raise HTTPException(status_code=404, detail="论文项目不存在")
    content, filename, media_type = result
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"
        },
    )


@router.get("/thesis/projects/{project_id}/export-readiness")
async def get_thesis_export_readiness(
    project_id: str,
    user: dict = Depends(require_thesis_access),
):
    try:
        return await stage_service.get_export_readiness(user["id"], project_id)
    except Exception as exc:  # noqa: BLE001
        _raise_http(exc)


@router.post("/thesis/projects/{project_id}/export")
async def export_thesis_package(
    project_id: str,
    allow_unconfirmed: bool = Query(default=False),
    user: dict = Depends(require_thesis_access),
):
    check_job_quota(user, "thesis_export")
    try:
        readiness = await stage_service.get_export_readiness(user["id"], project_id)
    except Exception as exc:  # noqa: BLE001 - map service errors to HTTP
        _raise_http(exc)
    warnings = readiness.get("warnings") or []
    if warnings and not allow_unconfirmed:
        labels = "、".join(str(item.get("label") or "") for item in warnings[:4])
        raise HTTPException(
            status_code=409,
            detail={
                "message": f"以下内容还没有作者确认：{labels}。确认后重新导出，或明确选择仍然导出。",
                "warnings": warnings,
            },
        )
    try:
        result = await service.export_project(user["id"], project_id)
    except Exception as exc:  # noqa: BLE001 - map service errors to HTTP
        _raise_http(exc)
    if result is None:
        raise HTTPException(status_code=404, detail="论文项目不存在")
    path, filename = result
    await log_audit(
        AuditAction.THESIS_EXPORT,
        user_id=str(user["id"]),
        details={
            "project_id": project_id,
            "filename": filename,
            "unconfirmed_warnings": len(warnings),
            "acknowledged": bool(warnings and allow_unconfirmed),
        },
    )
    return FileResponse(
        path,
        filename=filename,
        media_type="application/zip",
        # The zip is a one-shot download; remove it once the response is sent.
        background=BackgroundTask(lambda: path.unlink(missing_ok=True)),
    )


# ---------- Stage machine (M3) ----------
#
# The stage board is small on purpose: it records where the author is, what
# they wrote for that stage, and whether they confirmed exactly that content.
# It does not draft or accept anything on the author's behalf.

@router.get("/thesis/projects/{project_id}/stages", response_model=ThesisStagesOut)
async def get_thesis_stages(
    project_id: str,
    user: dict = Depends(require_thesis_access),
):
    try:
        return await stage_service.get_board(user["id"], project_id)
    except Exception as exc:  # noqa: BLE001
        _raise_http(exc)


@router.post(
    "/thesis/projects/{project_id}/stages/draft",
    response_model=ThesisStageDraftOut,
)
async def draft_thesis_stage(
    project_id: str,
    body: ThesisStageDraftIn,
    user: dict = Depends(require_thesis_access),
):
    """Draft the current stage note. The author must still save and confirm.

    This is deliberately not an "export a thesis" endpoint: it produces one
    stage's working text, keeps it out of the document until the author saves
    it, and never marks the stage accepted.
    """
    await ensure_token_budget(user)
    try:
        board = await stage_service.get_board(user["id"], project_id)
        project = await service.get_project(user["id"], project_id)
    except Exception as exc:  # noqa: BLE001
        _raise_http(exc)
    if project is None:
        raise HTTPException(status_code=404, detail="论文项目不存在")

    stage = str(board["state"].get("stage") or "topic")
    label = STAGE_LABELS.get(stage, stage)
    existing = str(board.get("current_content") or "").strip()
    requirements = body.requirements.strip()
    lines = [
        f"论文题目：{project.get('title') or '待补充'}",
    ]
    if project.get("school"):
        lines.append(f"学校：{project.get('school')}")
    if project.get("degree"):
        lines.append(f"学位：{project.get('degree')}")
    lines.append(f"当前阶段：{label}（{stage}）")
    lines.append(f"本阶段已有说明：{existing or '（空）'}")
    if requirements:
        lines.append(f"作者这一轮的要求：{requirements}")
    if body.word_count:
        lines.append(f"草稿长度：约 {body.word_count} 个中文字符。")
    else:
        lines.append("草稿长度：按阶段需要，不写整篇论文。")

    from app.core.llm.factory import get_llm

    try:
        llm = await get_llm(user["id"], purpose="write")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"模型不可用：{str(exc)[:200]}") from exc

    messages = [
        {"role": "system", "content": STAGE_DRAFT_PROMPT},
        {"role": "user", "content": "\n".join(lines)},
    ]
    parts: list[str] = []
    usage: dict | None = None
    try:
        async with asyncio.timeout(settings.llm_timeout):
            async for event in llm.astream_with_tools(messages, []):
                if isinstance(event, str):
                    parts.append(event)
                elif event.get("type") == "content":
                    parts.append(event.get("content") or "")
                elif event.get("type") == "usage":
                    value = event.get("usage")
                    if isinstance(value, dict):
                        usage = value
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"起草失败：{str(exc)[:200]}") from exc

    content = _clean_draft("".join(parts))
    if not content:
        raise HTTPException(status_code=502, detail="模型没有返回内容，阶段说明未改动。")
    try:
        await stage_service.record_draft(user["id"], project_id, content)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=502,
            detail="草稿已生成，但无法记录 AI 来源，因此没有返回内容。请稍后重试。",
        ) from exc
    if usage:
        from app.core.llm.usage import record_usage

        await record_usage(user["id"], None, usage, source="thesis")
    return ThesisStageDraftOut(
        stage=stage, label=label, content=content, usage=usage,
    )


@router.post("/thesis/projects/{project_id}/stages/content", response_model=ThesisStagesOut)
async def set_thesis_stage_content(
    project_id: str,
    body: ThesisStageContentIn,
    user: dict = Depends(require_thesis_access),
):
    try:
        return await stage_service.set_content(user["id"], project_id, body.content)
    except Exception as exc:  # noqa: BLE001
        _raise_http(exc)


@router.post("/thesis/projects/{project_id}/stages/readiness", response_model=ThesisStagesOut)
async def set_thesis_stage_readiness(
    project_id: str,
    body: ThesisStageReadinessIn,
    user: dict = Depends(require_thesis_access),
):
    try:
        return await stage_service.set_readiness(user["id"], project_id, body.readiness)
    except Exception as exc:  # noqa: BLE001
        _raise_http(exc)


@router.post("/thesis/projects/{project_id}/stages/confirm", response_model=ThesisStagesOut)
async def confirm_thesis_stage(
    project_id: str,
    body: ThesisStageConfirmIn,
    user: dict = Depends(require_thesis_access),
):
    try:
        return await stage_service.confirm_stage(user["id"], project_id, body.note)
    except Exception as exc:  # noqa: BLE001
        _raise_http(exc)


@router.post("/thesis/projects/{project_id}/stages/advance", response_model=ThesisStagesOut)
async def advance_thesis_stage(
    project_id: str,
    body: ThesisStageAdvanceIn,
    user: dict = Depends(require_thesis_access),
):
    try:
        return await stage_service.advance(user["id"], project_id, body.to_stage)
    except Exception as exc:  # noqa: BLE001
        _raise_http(exc)


@router.post("/thesis/projects/{project_id}/stages/return", response_model=ThesisStagesOut)
async def return_thesis_stage(
    project_id: str,
    body: ThesisStageReturnIn,
    user: dict = Depends(require_thesis_access),
):
    try:
        return await stage_service.return_to(user["id"], project_id, body.to_stage)
    except Exception as exc:  # noqa: BLE001
        _raise_http(exc)

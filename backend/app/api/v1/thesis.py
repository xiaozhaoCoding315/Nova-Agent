"""Thesis-mode endpoints: projects, DOCX import, scans and reports."""
from __future__ import annotations

from typing import NoReturn
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from starlette.background import BackgroundTask

from app.config import settings
from app.core.security.audit import AuditAction, log_audit
from app.core.security.auth import get_current_user
from app.core.security.limits import check_job_quota
from app.core.storage.user_storage import storage_limit_bytes
from app.core.thesis import service
from app.core.thesis.rules.builtin import list_templates
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
    ThesisTemplateOut,
)

router = APIRouter()


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
async def get_thesis_templates(user: dict = Depends(get_current_user)):
    return list_templates()


@router.get("/thesis/projects", response_model=list[ThesisProjectOut])
async def get_thesis_projects(user: dict = Depends(get_current_user)):
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


@router.post("/thesis/projects/{project_id}/export")
async def export_thesis_package(
    project_id: str,
    user: dict = Depends(require_thesis_access),
):
    check_job_quota(user, "thesis_export")
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
        details={"project_id": project_id, "filename": filename},
    )
    return FileResponse(
        path,
        filename=filename,
        media_type="application/zip",
        # The zip is a one-shot download; remove it once the response is sent.
        background=BackgroundTask(lambda: path.unlink(missing_ok=True)),
    )

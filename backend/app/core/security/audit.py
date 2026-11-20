import uuid
import json
from datetime import datetime
import structlog

logger = structlog.get_logger()

class AuditAction:
    LOGIN = "login"
    LOGIN_FAILED = "login_failed"
    CHAT_MESSAGE = "chat_message"
    TOOL_CALL = "tool_call"
    SANDBOX_RUN = "sandbox_run"
    RISK_BLOCKED = "risk_blocked"
    REPO_IMPORT = "repo_import"
    REPO_DELETE = "repo_delete"
    CHANGE_CREATED = "change_created"
    CHANGE_APPLIED = "change_applied"
    POLICY_DECISION = "policy_decision"
    HOOK_BLOCKED = "hook_blocked"
    DEPLOY = "deploy"
    DEPLOY_STOP = "deploy_stop"
    THESIS_PROJECT_CREATE = "thesis_project_create"
    THESIS_PROJECT_DELETE = "thesis_project_delete"
    THESIS_DOCUMENT_IMPORT = "thesis_document_import"
    THESIS_SCAN = "thesis_scan"
    THESIS_ISSUE_UPDATE = "thesis_issue_update"
    THESIS_FIX_APPLY = "thesis_fix_apply"
    THESIS_FIX_UNDO = "thesis_fix_undo"
    THESIS_CITATION_AUDIT = "thesis_citation_audit"
    THESIS_CITATION_METADATA = "thesis_citation_metadata"
    THESIS_REFERENCE_PDF_IMPORT = "thesis_reference_pdf_import"
    THESIS_REFERENCE_PDF_DELETE = "thesis_reference_pdf_delete"
    THESIS_CITATION_EVIDENCE_LOCATE = "thesis_citation_evidence_locate"
    THESIS_CITATION_EVIDENCE_UPDATE = "thesis_citation_evidence_update"
    THESIS_DISCLOSURE_CREATE = "thesis_disclosure_create"
    THESIS_DISCLOSURE_DELETE = "thesis_disclosure_delete"
    THESIS_EXPORT = "thesis_export"

# In-memory buffer for fast access
_audit_buffer = []
_BUFFER_SIZE = 1000


async def log_audit(action, user_id="anonymous", details=None, risk_level="safe"):
    entry = {
        "id": str(uuid.uuid4())[:12],
        "timestamp": datetime.now().isoformat(),
        "action": action,
        "user_id": user_id,
        "details": details or {},
        "risk_level": risk_level,
    }
    _audit_buffer.append(entry)
    if len(_audit_buffer) > _BUFFER_SIZE:
        del _audit_buffer[:500]
    # Persist to PostgreSQL (non-blocking — failure doesn't break the flow)
    try:
        from app.config import settings
        if settings.nova_test_fast:
            logger.info("audit_event", **entry)
            return entry["id"]
        from app.db import execute
        await execute(
            "INSERT INTO audit_log (id, action, user_id, details, risk_level) VALUES (%s, %s, %s, %s, %s)",
            (entry["id"], action, user_id, json.dumps(details or {}, ensure_ascii=False), risk_level)
        )
    except Exception as e:
        logger.warning("Audit persist failed", error=str(e))
    logger.info("audit_event", **entry)
    return entry["id"]


def get_audit_log(action=None, user_id=None, limit=100):
    filtered = _audit_buffer
    if action:
        filtered = [e for e in filtered if e["action"] == action]
    if user_id:
        filtered = [e for e in filtered if e["user_id"] == user_id]
    return filtered[-limit:]


def get_audit_stats():
    actions = {}
    for e in _audit_buffer:
        actions[e["action"]] = actions.get(e["action"], 0) + 1
    return {"total_entries": len(_audit_buffer), "by_action": actions}

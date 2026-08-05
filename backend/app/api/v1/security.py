from fastapi import APIRouter
from pydantic import BaseModel
from app.core.security.risk import grade_risk, RiskLevel
from app.core.security.validator import validate_prompt, validate_code
from app.core.security.audit import log_audit, get_audit_log, get_audit_stats

router = APIRouter()

class ValidateRequest(BaseModel):
    code: str = ""
    prompt: str = ""

@router.post("/security/validate")
async def security_validate(req: ValidateRequest):
    if req.code:
        risk, reasons = grade_risk(req.code)
        risk_level = risk.value
        blocked = risk == RiskLevel.BLOCK
        resp = {"input_type": "code", "risk_level": risk_level, "reasons": reasons}
    elif req.prompt:
        result = validate_prompt(req.prompt)
        risk_level = result.risk_level.value
        blocked = not result.valid
        resp = {"input_type": "prompt", **result.to_dict()}
    else:
        return {"error": "No input"}
    try:
        from app.core.security.audit import log_audit, AuditAction
        await log_audit(AuditAction.RISK_BLOCKED if blocked else "risk_checked", details={"risk_level": risk_level})
    except Exception:
        pass
    return resp

@router.get("/audit/log")
async def audit_log(action: str = None, limit: int = 100):
    return get_audit_log(action=action, limit=limit)

@router.get("/audit/stats")
async def audit_stats():
    return get_audit_stats()

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.core.sandbox.runtime import execute_in_sandbox, is_docker_available
from app.core.sandbox.config import SANDBOX_CONFIG

router = APIRouter()


class CodeExecutionRequest(BaseModel):
    code: str
    language: str = "python"
    inputs: str = ""
    timeout: int = 30


class CodeExecutionResponse(BaseModel):
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool
    sandboxed: bool


@router.post("/sandbox/execute", response_model=CodeExecutionResponse)
async def sandbox_execute(req: CodeExecutionRequest):
    """Execute code in a secure sandbox."""
    if len(req.code) > 50000:
        raise HTTPException(status_code=400, detail="Code too large (max 50KB)")
    result = await execute_in_sandbox(req.code, req.language, req.inputs, req.timeout)
    try:
        from app.core.security.audit import log_audit, AuditAction
        await log_audit(AuditAction.CODE_EXECUTION, details={"code": req.code[:100], "language": req.language}, risk_level="safe")
    except Exception:
        pass
    return result


@router.get("/sandbox/status")
async def sandbox_status():
    """Check sandbox availability."""
    return {
        "docker_available": is_docker_available(),
        "config": {
            "network_disabled": SANDBOX_CONFIG.network_disabled,
            "read_only": SANDBOX_CONFIG.read_only_root,
            "drop_all_capabilities": SANDBOX_CONFIG.drop_all_capabilities,
            "no_new_privileges": SANDBOX_CONFIG.no_new_privileges,
            "cpu_limit": SANDBOX_CONFIG.cpu_limit,
            "memory_limit": SANDBOX_CONFIG.memory_limit,
            "timeout": SANDBOX_CONFIG.timeout_seconds,
        }
    }

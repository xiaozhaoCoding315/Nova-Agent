"""Code executor skill: LLM-authored Python runs in the secure Docker sandbox.

Bridges the two strongest subsystems of the project: the Agent tool loop
(Function-Calling) and the hardened sandbox (network-off, read-only,
cap-drop ALL). The LLM can now write code to *verify* its answers instead
of guessing — the defining capability of a developer agent.
"""
import structlog

from app.core.sandbox.runtime import execute_in_sandbox
from app.core.security.validator import validate_code
from app.core.tools.base import Tool, ToolError

logger = structlog.get_logger()

_MAX_CODE_CHARS = 8000
# Leave headroom under the 30s harness tool timeout: sandbox gets 20s so
# a slow run returns a structured timeout result instead of tripping the
# outer fallback.
_SANDBOX_TIMEOUT_S = 20


async def execute_code(code: str) -> dict:
    """Tool handler: risk-check then execute Python in the sandbox."""
    if not code or not code.strip():
        raise ToolError("empty code")
    if len(code) > _MAX_CODE_CHARS:
        raise ToolError(f"code too long (max {_MAX_CODE_CHARS} chars)")

    validation = validate_code(code)
    if not validation.valid:
        raise ToolError(
            "code rejected by risk check: " + "; ".join(validation.messages)
        )

    result = await execute_in_sandbox(code, language="python", timeout=_SANDBOX_TIMEOUT_S)

    # 独立审计：与 API 直连沙箱执行共用 CODE_EXECUTION 动作
    try:
        from app.core.security.audit import log_audit, AuditAction
        await log_audit(
            AuditAction.CODE_EXECUTION,
            details={"source": "agent_tool", "code_head": code[:200],
                     "exit_code": result["exit_code"], "sandboxed": result["sandboxed"]},
            risk_level=validation.risk_level.value,
        )
    except Exception:
        pass

    return {
        "ok": result["exit_code"] == 0 and not result["timed_out"],
        "stdout": result["stdout"],
        "stderr": result["stderr"] or None,
        "exit_code": result["exit_code"],
        "timed_out": result["timed_out"],
        "sandboxed": result["sandboxed"],
    }


code_executor_tool = Tool(
    name="code_executor",
    description=(
        "Python 代码沙箱执行工具。在安全隔离的 Docker 容器中（禁用网络、"
        "只读文件系统、丢弃全部权限、20 秒超时）运行一段 Python 代码并返回"
        " stdout / stderr / exit_code。当你需要精确计算、验证逻辑、处理数据、"
        "测试正则或 JSON 解析等任何可以用代码确定结果的场景时，优先写代码调用本工具，"
        "不要凭记忆给出不确定的答案。代码中应直接 print 结果。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "要执行的完整 Python 代码，结果通过 print 输出，例如 print(sum(range(100)))",
            },
        },
        "required": ["code"],
    },
    handler=execute_code,
)

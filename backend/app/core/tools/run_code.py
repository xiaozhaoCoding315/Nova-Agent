"""run_code tool: execute code and tests in the locked-down Docker sandbox."""
from fastapi import HTTPException

from app.core.sandbox.runtime import execute as sandbox_execute, sandbox_status
from app.core.security.audit import AuditAction, log_audit
from app.core.security.limits import check_sandbox_quota
from app.core.security.risk import RiskLevel, grade_risk
from app.core.tools.base import ToolBusinessError, ToolContext, ToolDefinition


async def run_code(args: dict, ctx: ToolContext) -> dict:
    files = args.get("files") or {}
    if not isinstance(files, dict) or not files:
        raise ToolBusinessError(
            "files 必须是非空对象：{相对路径: 文件内容}，例如 {\"main.py\": \"print('hi')\"}"
        )

    code_blob = "\n".join(str(v) for v in files.values())
    level, reasons = grade_risk(code_blob)
    if level == RiskLevel.BLOCK:
        await log_audit(
            AuditAction.RISK_BLOCKED,
            user_id=str(ctx.user.get("id", "")) if ctx.user else "anonymous",
            details={"reasons": reasons[:5]},
            risk_level="block",
        )
        raise ToolBusinessError("代码被安全规则拦截：" + "；".join(reasons[:3]))

    status = await sandbox_status()
    if not status["available"]:
        raise ToolBusinessError(f"沙箱不可用（{status['reason']}），无法执行代码")

    if ctx.user:
        try:
            await check_sandbox_quota(ctx.user)
        except HTTPException as exc:
            raise ToolBusinessError(str(exc.detail))

    result = await sandbox_execute(
        files=files,
        command=args.get("command"),
        stdin=args.get("stdin", ""),
    )

    await log_audit(
        AuditAction.SANDBOX_RUN,
        user_id=str(ctx.user.get("id", "")) if ctx.user else "anonymous",
        details={
            "command": result.get("command"),
            "exit_code": result.get("exit_code"),
            "timed_out": result.get("timed_out"),
        },
    )

    return {
        "exit_code": result["exit_code"],
        "timed_out": result["timed_out"],
        "stdout": result["stdout"],
        "stderr": result["stderr"],
        "command": result["command"],
        "hint": "退出码 0 表示成功" if result["exit_code"] == 0 else "执行失败：请阅读 stderr，修正后重试",
    }


TOOL = ToolDefinition(
    name="run_code",
    description=(
        "在隔离沙箱中运行代码并返回真实的 stdout / stderr / 退出码。"
        "用途：验证代码是否正确、运行单元测试（command 设为 'python -m pytest -q'）、复现报错。"
        "沙箱环境：Python 3.12 + numpy + pytest，无网络，禁止访问外部资源。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "files": {
                "type": "object",
                "description": "写入沙箱的文件：{相对路径: 完整文件内容}，例如 {\"main.py\": \"...\", \"test_main.py\": \"...\"}",
            },
            "command": {
                "type": "string",
                "description": "运行命令（默认 python main.py）；跑测试用 python -m pytest -q",
            },
            "stdin": {"type": "string", "description": "标准输入内容（可选）"},
        },
        "required": ["files"],
    },
    func=run_code,
    timeout=45,
)
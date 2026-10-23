"""run_code tool: execute code and tests in the locked-down Docker sandbox."""
import os
import uuid
from pathlib import Path

from fastapi import HTTPException

from app.core.indexing.languages import SKIP_DIRS, is_supported
from app.core.sandbox.runtime import execute as sandbox_execute, sandbox_status
from app.core.security.audit import AuditAction, log_audit
from app.core.security.limits import check_sandbox_quota
from app.core.security.risk import RiskLevel, grade_risk
from app.core.tools.base import ToolBusinessError, ToolContext, ToolDefinition

REPO_COPY_MAX_FILES = 300
REPO_COPY_MAX_BYTES = 2_000_000
REPO_COPY_MAX_FILE_BYTES = 200_000


async def _collect_repo_files(repo_id: str, user: dict) -> dict[str, str]:
    """Copy the indexed repo workspace into the sandbox (bounded), so the
    model can run tests without pasting every source file."""
    from app.core.indexing.pipeline import get_repo

    repo = await get_repo(repo_id, user["id"])
    if not repo:
        raise ToolBusinessError("repo_id 不存在或无权访问")
    root = Path(repo["root_path"])
    if not root.is_dir():
        raise ToolBusinessError("仓库文件已不存在，请重新导入")

    files: dict[str, str] = {}
    total = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            path = Path(dirpath) / name
            rel = str(path.relative_to(root)).replace("\\", "/")
            if not is_supported(rel):
                continue
            try:
                size = path.stat().st_size
                if size == 0 or size > REPO_COPY_MAX_FILE_BYTES:
                    continue
                content = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            total += len(content)
            if len(files) >= REPO_COPY_MAX_FILES or total > REPO_COPY_MAX_BYTES:
                return files
            files[rel] = content
    return files


async def run_code(args: dict, ctx: ToolContext) -> dict:
    provided = args.get("files") or {}
    if not isinstance(provided, dict):
        raise ToolBusinessError("files 必须是对象：{相对路径: 文件内容}")

    files: dict[str, str] = {}
    repo_id = args.get("repo_id")
    if repo_id:
        try:
            uuid.UUID(str(repo_id))
        except ValueError:
            raise ToolBusinessError("repo_id 必须是 UUID")
        files.update(await _collect_repo_files(str(repo_id), ctx.user))
    files.update({str(k): str(v) for k, v in provided.items()})

    if not files:
        raise ToolBusinessError(
            "files 必须是非空对象：{相对路径: 文件内容}，例如 {\"main.py\": \"print('hi')\"}"
        )

    code_blob = "\n".join(files.values())
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
                "description": "额外写入沙箱的文件：{相对路径: 完整文件内容}；与 repo_id 同时使用时会覆盖同名仓库文件",
            },
            "repo_id": {
                "type": "string",
                "description": "可选：把该仓库文件整体复制进沙箱（便于直接运行仓库自带的测试）",
            },
            "command": {
                "type": "string",
                "description": "运行命令（默认 python main.py）；跑测试用 python -m pytest -q",
            },
            "stdin": {"type": "string", "description": "标准输入内容（可选）"},
        },
        "required": [],
    },
    func=run_code,
    timeout=45,
)
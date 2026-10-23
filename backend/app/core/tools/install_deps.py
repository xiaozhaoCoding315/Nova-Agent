"""install_deps tool: pip install requirements into the repo's persistent
deps volume. Admin-only and requires SANDBOX_ALLOW_NETWORK=true.

The install runs as root inside the sandbox with network, only the fixed
`pip install --target /deps -r <requirements>` command is allowed.
"""
import shlex
from pathlib import Path

from fastapi import HTTPException

from app.config import settings
from app.core.indexing.pipeline import get_repo
from app.core.sandbox.runtime import deps_volume_name, execute, sandbox_status
from app.core.security.audit import AuditAction, log_audit
from app.core.security.limits import check_sandbox_quota
from app.core.security.paths import UnsafePathError, resolve_repo_path
from app.core.tools.base import ToolBusinessError, ToolContext, ToolDefinition


async def install_deps(args: dict, ctx: ToolContext) -> dict:
    if ctx.user.get("role") != "admin":
        raise ToolBusinessError("只有管理员可以联网安装依赖（demo 账号不允许）")
    if not settings.sandbox_allow_network:
        raise ToolBusinessError("联网安装未开启：请在服务端 .env 设置 SANDBOX_ALLOW_NETWORK=true 后重启")

    repo_id = args.get("repo_id") or (ctx.repo_ids[0] if ctx.repo_ids else None)
    if not repo_id:
        raise ToolBusinessError("需要指定 repo_id，或先在会话中关联仓库")
    repo = await get_repo(str(repo_id), ctx.user["id"])
    if not repo:
        raise ToolBusinessError("仓库不存在或无权访问")

    try:
        rel = str(args.get("requirements") or "requirements.txt").replace("\\", "/")
        root = Path(repo["root_path"]).resolve()
        target = resolve_repo_path(root, rel)
    except (UnsafePathError, ValueError):
        raise ToolBusinessError("requirements 路径不合法")
    if not target.is_file():
        raise ToolBusinessError(f"未找到依赖文件：{rel}")

    status = await sandbox_status()
    if not status.get("builder_available"):
        raise ToolBusinessError("构建镜像未就绪：请先构建 nova-builder（docker build -f Dockerfile.builder -t nova-builder:latest .）")

    try:
        await check_sandbox_quota(ctx.user)
    except HTTPException as exc:
        raise ToolBusinessError(str(exc.detail))

    content = target.read_text(encoding="utf-8", errors="replace")
    command = f"pip install --target /deps -r {shlex.quote(rel)}"
    result = await execute(
        files={rel: content},
        command=command,
        timeout=settings.sandbox_install_timeout,
        image=settings.sandbox_builder_image,
        network=True,
        deps_volume=deps_volume_name(str(repo_id)),
        as_root=True,
    )
    await log_audit(
        AuditAction.SANDBOX_RUN,
        user_id=str(ctx.user.get("id", "")),
        details={"action": "install_deps", "repo_id": str(repo_id), "exit_code": result.get("exit_code")},
    )

    tail = (result.get("stdout", "") + "\n" + result.get("stderr", ""))[-4000:]
    if result.get("exit_code") != 0:
        raise ToolBusinessError(f"依赖安装失败（exit {result.get('exit_code')}）：\n{tail[-1500:]}")
    return {
        "installed": True,
        "requirements": rel,
        "command": command,
        "output_tail": tail[-1500:],
        "hint": "依赖已安装到该仓库的持久依赖卷，后续 run_code 会自动挂载。",
    }


TOOL = ToolDefinition(
    name="install_deps",
    description=(
        "把仓库 requirements.txt 中的依赖安装到该仓库的持久依赖卷（联网，仅管理员）。"
        "安装后 run_code 的 builder 环境会自动带上这些包。适用于仓库有额外依赖导致测试跑不起来时。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "repo_id": {"type": "string", "description": "仓库 UUID（可选，默认取会话关联仓库）"},
            "requirements": {"type": "string", "description": "requirements 文件路径，默认 requirements.txt"},
        },
        "required": [],
    },
    func=install_deps,
    category="execute",
    timeout=210,
)
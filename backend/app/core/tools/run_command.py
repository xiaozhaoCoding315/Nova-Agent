"""run_command tool: run a real shell command against the repo workspace,
inside a locked container whose /workspace IS the repository directory —
changes persist (scaffolding, git init/commit, file moves, builds).

Still sandboxed: no network by default, capabilities dropped, resource caps,
dangerous commands denied by the policy engine, readonly mode hard-blocked.
"""
from pathlib import Path

from fastapi import HTTPException

from app.config import settings
from app.core.sandbox.runtime import deps_volume_name, execute as sandbox_execute, sandbox_status
from app.core.security.audit import AuditAction, log_audit
from app.core.security.limits import check_sandbox_quota
from app.core.tools.base import ToolBusinessError, ToolContext, ToolDefinition


async def run_command(args: dict, ctx: ToolContext) -> dict:
    command = str(args.get("command") or "").strip()
    if not command:
        raise ToolBusinessError("command 不能为空")
    repo_id = args.get("repo_id") or (ctx.repo_ids[0] if ctx.repo_ids else None)
    if not repo_id:
        raise ToolBusinessError("需要指定 repo_id，或先在会话中关联仓库")

    from app.core.indexing.pipeline import get_repo
    repo = await get_repo(str(repo_id), ctx.user["id"])
    if not repo:
        raise ToolBusinessError("仓库不存在或无权访问")
    root = Path(repo["root_path"]).resolve()
    if not root.is_dir():
        raise ToolBusinessError("仓库文件已不存在，请重新导入")

    # No grade_risk here: the payload IS a shell command by design (&& pipes
    # are legitimate); dangerous commands are denied by the policy engine's
    # regex layer and the blast radius is the sandbox (no network, caps
    # dropped, only this repo directory mounted).

    status = await sandbox_status()
    if not status["available"]:
        raise ToolBusinessError(f"沙箱不可用（{status['reason']}），无法执行命令")

    if ctx.user:
        try:
            await check_sandbox_quota(ctx.user)
        except HTTPException as exc:
            raise ToolBusinessError(str(exc.detail))

    use_node = args.get("env") == "node"
    if use_node:
        if not status.get("node_available"):
            raise ToolBusinessError(f"node 沙箱镜像未就绪：请构建 {settings.sandbox_node_image}")
        image = settings.sandbox_node_image
        deps = deps_volume_name(str(repo_id), "node")
        deps_mount = "/workspace/node_modules"
    else:
        image = settings.sandbox_builder_image if status.get("builder_available") else settings.sandbox_image
        deps = deps_volume_name(str(repo_id))
        deps_mount = None

    result = await sandbox_execute(
        files={},
        command=command,
        timeout=min(int(args.get("timeout") or 120), 300),
        image=image,
        deps_volume=deps,
        deps_mount=deps_mount,
        workspace_dir=str(root),
        user="10001:10001",
    )

    await log_audit(
        AuditAction.SANDBOX_RUN,
        user_id=str(ctx.user.get("id", "")) if ctx.user else "anonymous",
        details={
            "command": result.get("command"),
            "exit_code": result.get("exit_code"),
            "timed_out": result.get("timed_out"),
            "persisted": True,
        },
    )

    ok = result["exit_code"] == 0 and not result["timed_out"]
    return {
        "exit_code": result["exit_code"],
        "timed_out": result["timed_out"],
        "stdout": result["stdout"],
        "stderr": result["stderr"],
        "command": result["command"],
        "persisted": True,
        "hint": (
            "改动已写入仓库工作区；如新增/删除了文件，建议让用户在项目面板点「重建索引」"
            if ok else
            "执行失败：请阅读 stderr，修正命令后重试"
        ),
    }


TOOL = ToolDefinition(
    name="run_command",
    description=(
        "在仓库工作区里执行真实 shell 命令（隔离容器内，无网络），改动直接保留在仓库中。"
        "适合：脚手架（npm create vite@latest）、git init/commit、移动/删除文件、跑构建脚本、"
        "批量文本处理。只读模式会被拒绝；git push 等危险命令会被策略拦截。"
        "与 run_code 的区别：run_code 在一次性副本里验证代码，本工具的修改会持久化。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "要执行的 shell 命令，工作目录为仓库根，如 'git init && git add -A && git commit -m init'",
            },
            "repo_id": {"type": "string", "description": "仓库 UUID（可选，默认取会话关联仓库）"},
            "env": {"type": "string", "description": "运行环境镜像：builder（Python 工具链，默认）或 node（Node 20）"},
            "timeout": {"type": "integer", "description": "超时秒数（默认 120，最大 300）"},
        },
        "required": ["command"],
    },
    func=run_command,
    category="execute",
    capabilities=["proc.exec", "fs.write"],
    timeout=310,
)

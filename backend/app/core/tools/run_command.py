"""run_command tool: run a real shell command against the repo workspace,
inside a locked container whose /workspace IS the repository directory —
changes persist (scaffolding, git init/commit, file moves, builds).

Still sandboxed: no network by default, capabilities dropped, resource caps,
dangerous commands denied by the policy engine, readonly mode hard-blocked.
In readonly/ask mode the command runs against a sanitized copy without secret
files, so a classification miss cannot read credentials or mutate the repo.
"""
import asyncio
import re
from pathlib import Path

from fastapi import HTTPException

from app.config import settings
from app.core.sandbox.runtime import deps_volume_name, execute as sandbox_execute, sandbox_status
from app.core.security.audit import AuditAction, log_audit
from app.core.security.commands import CommandClass, classify_command
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

    if settings.use_host_executor:
        return await _run_host_command(command, root=root, ctx=ctx, args=args)

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

    # 只读命令在所有模式下都跑净化副本（自动模式也可能被注入读写密钥）。
    # auto/full 的写命令保留真实工作区，但遮蔽密钥文件；git 诊断需要 .git。
    command_class, _reason = classify_command(command)
    approved_ask = (
        ctx.permission_mode == "ask" and getattr(ctx, "approval_granted", False)
    )
    isolated = command_class is CommandClass.READONLY or (
        ctx.permission_mode in ("readonly", "ask") and not approved_ask
    )
    mask_secrets = (
        settings.sandbox_mask_secrets
        and not isolated
        and (ctx.permission_mode in ("auto", "full") or approved_ask)
    )
    include_git = bool(re.search(r"(?:^|[;&|])\s*git(?:\s|$)", command, re.MULTILINE))

    on_output = None
    if ctx.output_queue is not None:
        loop = asyncio.get_running_loop()
        queue_ref = ctx.output_queue

        def on_output(stream: str, text: str) -> None:
            loop.call_soon_threadsafe(queue_ref.put_nowait, (stream, text))

    result = await sandbox_execute(
        files={},
        command=command,
        timeout=min(int(args.get("timeout") or 120), 300),
        image=image,
        deps_volume=deps,
        deps_mount=deps_mount,
        workspace_dir=str(root),
        user="10001:10001",
        sanitized_workspace=isolated,
        include_git=include_git,
        mask_secrets=mask_secrets,
        on_output=on_output,
        job_id=ctx.tool_call_id or None,
        user_label=str(ctx.user.get("id", "")) or None,
    )
    persisted = not isolated

    await log_audit(
        AuditAction.SANDBOX_RUN,
        user_id=str(ctx.user.get("id", "")) if ctx.user else "anonymous",
        details={
            "command": result.get("command"),
            "exit_code": result.get("exit_code"),
            "timed_out": result.get("timed_out"),
            "persisted": persisted,
            "isolated": isolated,
            "masked_secrets": mask_secrets,
        },
    )

    ok = result["exit_code"] == 0 and not result["timed_out"]
    if not persisted:
        hint = (
            "命令被判定为只读，已在净化副本中执行，未改动真实仓库；"
            "如需写入，请使用明确的写命令（如 git commit / npm install）"
            if ok else
            "执行失败：请阅读 stderr，修正命令后重试"
        )
    else:
        hint = (
            "改动已写入仓库工作区；如新增/删除了文件，建议让用户在项目面板点「重建索引」"
            if ok else
            "执行失败：请阅读 stderr，修正命令后重试"
        )
    return {
        "exit_code": result["exit_code"],
        "timed_out": result["timed_out"],
        "stdout": result["stdout"],
        "stderr": result["stderr"],
        "command": result["command"],
        "persisted": persisted,
        "isolated": isolated,
        "hint": hint,
    }


async def _run_host_command(
    command: str, *, root: Path, ctx: ToolContext, args: dict
) -> dict:
    """Local-mode branch: run on the host with no container isolation.

    The policy gate (``decide_tool``) has already run in
    ``ToolRegistry.execute``: ask/deny rules, readonly-command allowlist and
    the secret-path scan all apply exactly as in server mode.  The command
    runs as the signed-in user in the project directory — that is the
    product's local-mode promise, and every result says so.
    """
    from app.core.exec.service import run_command_host

    on_output = None
    if ctx.output_queue is not None:
        loop = asyncio.get_running_loop()
        queue_ref = ctx.output_queue

        def on_output(stream: str, text: str) -> None:
            loop.call_soon_threadsafe(queue_ref.put_nowait, (stream, text))

    result = await run_command_host(
        command,
        root=root,
        timeout=max(1, min(int(args.get("timeout") or 120), 300)),
        on_output=on_output,
        job_id=ctx.tool_call_id or None,
        user_id=ctx.user.get("id"),
    )
    await log_audit(
        AuditAction.SANDBOX_RUN,
        user_id=str(ctx.user.get("id", "")) if ctx.user else "anonymous",
        details={
            "executor": "host",
            "exit_code": result.get("exit_code"),
            "timed_out": result.get("timed_out"),
            "kill_failed": bool(result.get("kill_failed")),
            "persisted": True,
            "isolated": False,
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
        "isolated": False,
        "sandboxed": False,
        "isolation": "none",
        "executor": "host",
        "warning": result["warning"],
        "hint": (
            "命令已在你的项目目录真实执行；如需保留改动请检查 git diff"
            if ok else
            "执行失败：请阅读 stderr，修正命令后重试"
        ),
    }


_SERVER_DESCRIPTION = (
    "在仓库工作区里执行真实 shell 命令（隔离容器内，无网络），改动直接保留在仓库中。"
    "适合：脚手架、安装依赖、跑构建脚本、批量文本处理。"
    "只读模式下只放行只读命令（git status/diff/log、ls、grep 等）；"
    "确认模式下写命令会先请求用户批准，批准后在遮蔽密钥的工作区执行。"
    "与 run_code 的区别：run_code 在一次性副本里验证代码，本工具的修改会持久化。"
)

_LOCAL_DESCRIPTION = (
    "在当前项目目录执行真实 shell 命令，改动直接保留在仓库中。"
    "适合：脚手架、安装依赖、跑构建脚本、批量文本处理。"
    "本地模式警告：无容器隔离，命令以当前 Windows 用户权限在你的电脑上运行，"
    "可使用主机网络；后台或脱离终端的进程可能在命令结束后继续运行，"
    "且命令结束后无法再通过 job_id 取消。"
    "确认模式下每条 run_command 都需要你批准；本地执行不做净化副本或密钥遮蔽。"
    "与 run_code 的区别：run_code 在一次性临时目录里验证代码，本工具的修改会持久化。"
)


def tool_description() -> str:
    """Model-facing text; the local runtime is set at process startup."""
    return _LOCAL_DESCRIPTION if settings.is_local else _SERVER_DESCRIPTION


TOOL = ToolDefinition(
    name="run_command",
    description=tool_description(),
    parameters={
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "要执行的 shell 命令，工作目录为仓库根，如 'git init && git add -A && git commit -m init'",
            },
            "repo_id": {"type": "string", "description": "仓库 UUID（可选，默认取会话关联仓库）"},
            "env": {
                "type": "string",
                "enum": ["builder", "node"],
                "description": "运行环境镜像：builder（Python 工具链，默认）或 node（Node 20）",
            },
            "timeout": {"type": "integer", "description": "超时秒数（默认 120，最大 300）"},
        },
        "required": ["command"],
    },
    func=run_command,
    category="execute",
    capabilities=["proc.exec", "fs.write"],
    timeout=310,
)

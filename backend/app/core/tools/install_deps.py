"""install_deps tool: install Python or Node dependencies into a repo's
persistent dependency volume. Admin-only and requires
SANDBOX_ALLOW_NETWORK=true.

Only fixed install commands are allowed: pip install -r, npm ci/install,
pnpm install, or yarn install.
"""
import shlex
from pathlib import Path

from fastapi import HTTPException

from app.config import settings
from app.core.exec.host import execute_host, project_python, quote_shell_arg
from app.core.indexing.pipeline import get_repo
from app.core.sandbox.runtime import deps_volume_name, execute, sandbox_status
from app.core.security.audit import AuditAction, log_audit
from app.core.security.limits import check_sandbox_quota
from app.core.security.paths import (
    UnsafePathError,
    resolve_repo_path,
    try_normalize_relpath,
)
from app.core.tools.base import ToolBusinessError, ToolContext, ToolDefinition

NODE_LOCKFILES = ("package-lock.json", "pnpm-lock.yaml", "yarn.lock")


def _read_repo_file(root: Path, rel: str) -> str | None:
    try:
        target = resolve_repo_path(root, rel)
    except (UnsafePathError, ValueError):
        return None
    if not target.is_file():
        return None
    return target.read_text(encoding="utf-8", errors="replace")


async def install_deps(args: dict, ctx: ToolContext) -> dict:
    if settings.is_local:
        return await _install_deps_local(args, ctx)

    is_admin = ctx.user.get("role") == "admin"
    # Admins can always install; regular users may opt in per-session via the
    # "full access" permission mode (the server-side network flag still applies).
    if not is_admin and ctx.permission_mode != "full":
        raise ToolBusinessError("联网安装依赖需要管理员，或在会话中切换到「完全访问」模式")
    if not settings.sandbox_allow_network:
        raise ToolBusinessError("联网安装未开启：请在服务端 .env 设置 SANDBOX_ALLOW_NETWORK=true 后重启")

    repo_id = args.get("repo_id") or (ctx.repo_ids[0] if ctx.repo_ids else None)
    if not repo_id:
        raise ToolBusinessError("需要指定 repo_id，或先在会话中关联仓库")
    repo = await get_repo(str(repo_id), ctx.user["id"])
    if not repo:
        raise ToolBusinessError("仓库不存在或无权访问")

    kind = "node" if str(args.get("kind") or "").lower() == "node" else "python"
    default_manifest = "package.json" if kind == "node" else "requirements.txt"
    rel = str(args.get("requirements") or default_manifest).replace("\\", "/")
    if kind == "node" and rel.lower().endswith("requirements.txt"):
        kind = "python"
    root = Path(repo["root_path"]).resolve()

    status = await sandbox_status()
    try:
        await check_sandbox_quota(ctx.user)
    except HTTPException as exc:
        raise ToolBusinessError(str(exc.detail))

    if kind == "node":
        if "/" in rel:
            raise ToolBusinessError("Node 依赖安装目前只支持仓库根目录 package.json（子包/monorepo 在 P2.3 支持）")
        if not status.get("node_available"):
            raise ToolBusinessError(
                f"node 镜像未就绪：请先构建 {settings.sandbox_node_image}"
            )
        files: dict[str, str] = {}
        manifest = _read_repo_file(root, rel)
        if manifest is None:
            raise ToolBusinessError(f"未找到 Node 依赖文件：{rel}")
        files[rel] = manifest
        for lock in NODE_LOCKFILES:
            content = _read_repo_file(root, lock)
            if content is not None:
                files[lock] = content
        if "pnpm-lock.yaml" in files:
            command = "corepack pnpm install --frozen-lockfile"
        elif "yarn.lock" in files:
            command = "corepack yarn install --immutable"
        elif "package-lock.json" in files:
            command = "npm ci --no-audit --no-fund"
        else:
            command = "npm install --no-audit --no-fund"
        result = await execute(
            files=files,
            command=command,
            timeout=max(settings.sandbox_install_timeout, 300),
            image=settings.sandbox_node_image,
            network=True,
            deps_volume=deps_volume_name(str(repo_id), "node"),
            deps_mount="/workspace/node_modules",
            as_root=True,
        )
        audit_details = {
            "action": "install_deps", "kind": "node",
            "repo_id": str(repo_id), "manifest": rel,
            "exit_code": result.get("exit_code"),
        }
        success_hint = "依赖已安装到该仓库的 Node 依赖卷，后续 verify/run_code 会自动挂载 node_modules。"
    else:
        if not status.get("builder_available"):
            raise ToolBusinessError(
                "构建镜像未就绪：请先构建 nova-builder（docker build -f Dockerfile.builder -t nova-builder:latest .）"
            )
        content = _read_repo_file(root, rel)
        if content is None:
            raise ToolBusinessError(f"未找到依赖文件：{rel}")
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
        audit_details = {
            "action": "install_deps", "kind": "python",
            "repo_id": str(repo_id), "manifest": rel,
            "exit_code": result.get("exit_code"),
        }
        success_hint = "依赖已安装到该仓库的持久依赖卷，后续 run_code 的 builder 环境会自动挂载。"

    await log_audit(
        AuditAction.SANDBOX_RUN,
        user_id=str(ctx.user.get("id", "")),
        details=audit_details,
    )

    tail = (result.get("stdout", "") + "\n" + result.get("stderr", ""))[-4000:]
    if result.get("exit_code") != 0:
        raise ToolBusinessError(f"依赖安装失败（exit {result.get('exit_code')}）：\n{tail[-1500:]}")
    return {
        "installed": True,
        "kind": kind,
        "manifest": rel,
        "command": command,
        "output_tail": tail[-1500:],
        "hint": success_hint,
    }


async def _install_deps_local(args: dict, ctx: ToolContext) -> dict:
    """Install into the project's own .venv / node_modules on the host."""
    mode = getattr(ctx, "permission_mode", "auto")
    if mode == "readonly":
        raise ToolBusinessError(
            "本地模式下只读/计划权限不执行主机命令，请切换到确认模式后再执行"
        )
    if not settings.local_allow_install_deps:
        raise ToolBusinessError(
            "本地模式默认禁用依赖安装；如需开启，请在 nova-config.json 设置 allowInstallDeps=true 后重启"
        )
    if not getattr(ctx, "approval_granted", False):
        raise ToolBusinessError("本地安装依赖需要你批准")

    repo_id = args.get("repo_id") or (ctx.repo_ids[0] if ctx.repo_ids else None)
    if not repo_id:
        raise ToolBusinessError("需要指定 repo_id，或先在会话中关联仓库")
    repo = await get_repo(str(repo_id), ctx.user["id"])
    if not repo:
        raise ToolBusinessError("仓库不存在或无权访问")
    root = Path(repo["root_path"]).resolve()

    kind = "node" if str(args.get("kind") or "").lower() == "node" else "python"
    default_manifest = "package.json" if kind == "node" else "requirements.txt"
    raw_rel = str(args.get("requirements") or default_manifest)
    rel = try_normalize_relpath(raw_rel)
    if not rel:
        raise ToolBusinessError("依赖文件路径不安全")
    if kind == "node" and rel.lower().endswith("requirements.txt"):
        kind = "python"

    if kind == "python":
        python = project_python(root)
        if python is None:
            raise ToolBusinessError(
                "未找到项目虚拟环境 .venv；请先在项目目录创建 .venv 并安装 pip"
            )
        if _read_repo_file(root, rel) is None:
            raise ToolBusinessError(f"未找到依赖文件：{rel}")
        try:
            command = (
                f"{quote_shell_arg(str(python))} -m pip install -r "
                f"{quote_shell_arg(rel)}"
            )
        except ValueError as exc:
            raise ToolBusinessError(f"依赖文件路径不安全：{exc}") from exc
    else:
        if "/" in rel:
            raise ToolBusinessError("Node 依赖安装目前只支持仓库根目录 package.json")
        files: dict[str, str] = {}
        manifest = _read_repo_file(root, rel)
        if manifest is None:
            raise ToolBusinessError(f"未找到 Node 依赖文件：{rel}")
        for lock in NODE_LOCKFILES:
            content = _read_repo_file(root, lock)
            if content is not None:
                files[lock] = content
        if "pnpm-lock.yaml" in files:
            command = "corepack pnpm install --frozen-lockfile"
        elif "yarn.lock" in files:
            command = "corepack yarn install --immutable"
        elif "package-lock.json" in files:
            command = "npm ci --no-audit --no-fund"
        else:
            command = "npm install --no-audit --no-fund"

    try:
        result = await execute_host(
            command,
            root=root,
            timeout=max(settings.sandbox_install_timeout, 300),
            job_id=ctx.tool_call_id or None,
            user_id=ctx.user.get("id"),
        )
    except (ValueError, OSError) as exc:
        raise ToolBusinessError(f"依赖安装失败：{exc}") from exc
    await log_audit(
        AuditAction.SANDBOX_RUN,
        user_id=str(ctx.user.get("id", "")),
        details={
            "action": "install_deps", "kind": kind, "repo_id": str(repo_id),
            "manifest": rel, "exit_code": result.get("exit_code"),
            "executor": "host",
        },
    )
    tail = (result.get("stdout", "") + "\n" + result.get("stderr", ""))[-4000:]
    if result.get("exit_code") != 0:
        raise ToolBusinessError(
            f"依赖安装失败（exit {result.get('exit_code')}）：\n{tail[-1500:]}"
        )
    hint = (
        "依赖已安装到项目自身的 .venv；后续 Python 验证会直接使用该环境。"
        "本地模式暂不支持 Node/前端验证。"
        if kind == "python" else
        "依赖已安装到项目自身的 node_modules；本地模式暂不支持 Node/前端验证，"
        "请在服务器模式运行验证或手动执行。"
    )
    return {
        "installed": True,
        "kind": kind,
        "manifest": rel,
        "command": command,
        "output_tail": tail[-1500:],
        "isolation": "none",
        "hint": hint,
    }


_SERVER_DESCRIPTION = (
    "把仓库依赖安装到该仓库的持久依赖卷（联网，仅管理员）。"
    "Python 读取 requirements.txt；Node 读取 package.json + lockfile（npm/pnpm/yarn）。"
    "安装后 verify 与 run_code 会自动挂载对应依赖卷。"
)
_LOCAL_DESCRIPTION = (
    "把依赖安装到当前项目自身的 .venv / node_modules（联网）。"
    "本地模式默认禁用：需在 nova-config.json 设置 allowInstallDeps=true 后重启，"
    "且每次安装都需要你批准后才会执行。"
)


def tool_description() -> str:
    """Model-facing text; the local runtime is set at process startup."""
    return _LOCAL_DESCRIPTION if settings.is_local else _SERVER_DESCRIPTION


TOOL = ToolDefinition(
    name="install_deps",
    description=tool_description(),
    parameters={
        "type": "object",
        "properties": {
            "repo_id": {"type": "string", "description": "仓库 UUID（可选，默认取会话关联仓库）"},
            "kind": {
                "type": "string",
                "description": "依赖类型：python（默认）或 node",
            },
            "requirements": {
                "type": "string",
                "description": "Python requirements 文件或 Node package.json 路径；默认按 kind 选择",
            },
        },
        "required": [],
    },
    func=install_deps,
    category="execute",
    timeout=360,
)

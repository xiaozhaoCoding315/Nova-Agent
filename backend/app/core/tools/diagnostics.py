"""diagnostics tool: fixed-argv ruff / mypy / tsc with structured output.

The model chooses the runner, an optional repo and target paths; it cannot
inject flags or executables.  Server mode runs in the builder/node sandbox on
a sanitized copy; local mode runs the resolved host binary with shell=False
and marks the result as having no container isolation.
"""
import re
import shlex
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from fastapi import HTTPException

from app.config import settings
from app.core.sandbox.runtime import (
    deps_volume_name,
    sandbox_status,
)
from app.core.sandbox.runtime import (
    execute as sandbox_execute,
)
from app.core.security.audit import AuditAction, log_audit
from app.core.security.limits import check_sandbox_quota
from app.core.tools.base import ToolBusinessError, ToolContext, ToolDefinition
from app.core.tools.diagnostics_parse import (
    parse_mypy_text,
    parse_ruff_json,
    parse_tsc_text,
    sort_diagnostics,
    summarize,
    tail_text,
)

TOOL_NAME = "diagnostics"
MAX_PATHS = 20
DEFAULT_MAX_RESULTS = 200
MAX_RESULTS = 500
DEFAULT_TIMEOUT = 120
MAX_TIMEOUT = 300
TOOL_TIMEOUT = MAX_TIMEOUT + 20
VERSION_TTL_SECONDS = 3600

_TOOL_SPECS = {
    "ruff": {
        "version": "0.8.6",
        "summary": "Python lint（ruff check，JSON 输出）",
    },
    "mypy": {"version": "1.13.0", "summary": "Python 类型检查（mypy）"},
    "tsc": {"version": "5.6.3", "summary": "TypeScript 类型检查（tsc --noEmit）"},
}
_PARSERS = {
    "ruff": parse_ruff_json,
    "mypy": parse_mypy_text,
    "tsc": parse_tsc_text,
}
_OK_EXIT_CODES = {"ruff": {0, 1}, "mypy": {0, 1}, "tsc": {0, 1, 2}}
_VERSION_CACHE: dict[tuple[str, ...], tuple[float, str]] = {}


def build_argv(
    tool: str, paths: list[str], project: str, cache_dir: str
) -> list[str]:
    if tool == "ruff":
        return [
            "ruff", "check", "--output-format", "json", "--no-cache",
            "--quiet", *(paths or ["."]),
        ]
    if tool == "mypy":
        return [
            "mypy", "--no-incremental", "--no-error-summary",
            "--show-column-numbers", "--show-error-codes",
            "--no-color-output", "--cache-dir", cache_dir,
            *(paths or ["."]),
        ]
    if tool == "tsc":
        return [
            "tsc", "--noEmit", "--incremental", "false",
            "--pretty", "false", "-p", project,
        ]
    raise ToolBusinessError("tool 必须是 ruff、mypy 或 tsc")


def _venv_bins(root: Path) -> list[Path]:
    return [
        root / ".venv" / "Scripts",
        root / ".venv" / "bin",
        root / "backend" / ".venv" / "Scripts",
        root / "backend" / ".venv" / "bin",
    ]


def resolve_host_argv(
    tool: str, root: Path, base_argv: list[str]
) -> list[str]:
    """Resolve only known install locations / PATH; never a model path."""
    if tool in ("ruff", "mypy"):
        for bin_dir in _venv_bins(root):
            for filename in (f"{tool}.exe", tool):
                candidate = bin_dir / filename
                if candidate.is_file():
                    return [str(candidate), *base_argv[1:]]
        found = shutil.which(tool)
        if not found:
            raise ToolBusinessError(
                f"本机未找到 {tool}：请在项目虚拟环境安装"
                f"（pip install {tool}），或改用容器模式"
            )
        return [found, *base_argv[1:]]

    node = shutil.which("node")
    if not node:
        raise ToolBusinessError(
            "本机未找到 node：请安装 Node.js，或改用容器模式"
        )
    for base in (root / "frontend", root):
        script = base / "node_modules" / "typescript" / "bin" / "tsc"
        if script.is_file():
            return [node, str(script), *base_argv[1:]]
    raise ToolBusinessError(
        "本机未找到 typescript：请先在项目里 npm install，或改用容器模式"
    )


def _display_argv(argv: list[str], *, posix: bool) -> str:
    if posix:
        return shlex.join(argv)
    return subprocess.list2cmdline(argv)


def _validate_paths(args: dict, root: Path) -> list[str]:
    raw = args.get("paths") or []
    if not isinstance(raw, list) or len(raw) > MAX_PATHS:
        raise ToolBusinessError(f"paths 必须是最多 {MAX_PATHS} 项的数组")
    paths: list[str] = []
    for item in raw:
        text = str(item or "").strip().replace("\\", "/")
        if not text:
            raise ToolBusinessError("paths 不能包含空路径")
        if text.startswith("/") or re.match(r"^[A-Za-z]:", text):
            raise ToolBusinessError(f"paths 必须是仓库内相对路径：{item}")
        candidate = (root / text).resolve(strict=False)
        if candidate != root and root not in candidate.parents:
            raise ToolBusinessError(f"paths 越出仓库目录：{item}")
        paths.append(text)
    return paths


def _tsc_project(args: dict, root: Path) -> str:
    raw = str(args.get("project") or "tsconfig.json").strip().replace(
        "\\", "/"
    )
    if raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
        raise ToolBusinessError("project 必须是仓库内相对路径")
    candidate = (root / raw).resolve(strict=False)
    if candidate != root and root not in candidate.parents:
        raise ToolBusinessError("project 越出仓库目录")
    if not candidate.is_file():
        raise ToolBusinessError(
            f"tsconfig 不存在：{raw}；请传 project 指向仓库内 tsconfig"
        )
    return raw


def _limits(args: dict) -> tuple[int, int]:
    raw_results = args.get("max_results", DEFAULT_MAX_RESULTS)
    if not isinstance(raw_results, int) or isinstance(raw_results, bool):
        raise ToolBusinessError("max_results 必须是整数")
    raw_timeout = args.get("timeout", DEFAULT_TIMEOUT)
    if not isinstance(raw_timeout, int) or isinstance(raw_timeout, bool):
        raise ToolBusinessError("timeout 必须是整数")
    return (
        max(1, min(raw_results, MAX_RESULTS)),
        max(1, min(raw_timeout, MAX_TIMEOUT)),
    )


def _version_argv(tool: str, argv: list[str]) -> list[str]:
    head = argv[:2] if tool == "tsc" else argv[:1]
    return [*head, "--version"]


async def _version_for(tool: str, argv: list[str], *, root: Path) -> str:
    probe = _version_argv(tool, argv)
    key = tuple(probe)
    now = time.monotonic()
    cached = _VERSION_CACHE.get(key)
    if cached and now - cached[0] < VERSION_TTL_SECONDS:
        return cached[1]
    from app.core.exec.service import run_argv_host

    try:
        result = await run_argv_host(probe, root=root, timeout=10)
    except ToolBusinessError:
        raise ToolBusinessError(
            f"无法运行 {tool} 的版本探测，请确认本机已安装或改用容器模式"
        ) from None
    lines = (result.get("stdout") or result.get("stderr") or "").strip().splitlines()
    if not lines:
        raise ToolBusinessError(f"无法识别 {tool} 版本，请确认安装是否完整")
    version = lines[0][:80]
    _VERSION_CACHE[key] = (now, version)
    return version


async def _run_sandbox(
    tool: str,
    argv: list[str],
    *,
    root: Path,
    repo_id: str,
    timeout: int,
    ctx: ToolContext,
) -> dict:
    status = await sandbox_status()
    if not status["available"]:
        raise ToolBusinessError(
            f"沙箱不可用（{status['reason']}），无法运行诊断"
        )
    if ctx.user:
        try:
            await check_sandbox_quota(ctx.user)
        except HTTPException as exc:
            raise ToolBusinessError(str(exc.detail))
    if tool == "tsc":
        if not status.get("node_available"):
            raise ToolBusinessError(
                f"node 沙箱镜像未就绪：请构建 {settings.sandbox_node_image}"
            )
        image = settings.sandbox_node_image
        deps = deps_volume_name(str(repo_id), "node")
        deps_mount = "/workspace/node_modules"
    else:
        image = (
            settings.sandbox_builder_image
            if status.get("builder_available")
            else settings.sandbox_image
        )
        deps = deps_volume_name(str(repo_id))
        deps_mount = None
    command = _display_argv(argv, posix=True)
    result = await sandbox_execute(
        files={},
        command=command,
        timeout=timeout,
        image=image,
        deps_volume=deps,
        deps_mount=deps_mount,
        workspace_dir=str(root),
        user="10001:10001",
        sanitized_workspace=True,
        include_git=False,
        job_id=ctx.tool_call_id or None,
        user_label=str(ctx.user.get("id", "")) or None,
    )
    result["executor"] = "sandbox"
    result["version"] = _TOOL_SPECS[tool]["version"]
    result["command"] = command
    return result


async def _run_host(
    tool: str,
    argv: list[str],
    *,
    root: Path,
    timeout: int,
    ctx: ToolContext,
) -> dict:
    from app.core.exec.service import run_argv_host

    version = await _version_for(tool, argv, root=root)
    result = await run_argv_host(
        argv,
        root=root,
        timeout=timeout,
        job_id=ctx.tool_call_id or None,
        user_id=ctx.user.get("id"),
    )
    result["executor"] = "host"
    result["version"] = version
    return result


async def run_diagnostics(args: dict, ctx: ToolContext) -> dict:
    tool = str(args.get("tool") or "").strip()
    if tool not in _TOOL_SPECS:
        raise ToolBusinessError("tool 必须是 ruff、mypy 或 tsc")
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

    max_results, timeout = _limits(args)
    paths = _validate_paths(args, root)
    project = _tsc_project(args, root) if tool == "tsc" else ""

    host_tmp: str | None = None
    try:
        if tool == "mypy" and settings.use_host_executor:
            host_tmp = tempfile.mkdtemp(prefix="nova-mypy-")
            cache_dir = host_tmp
        else:
            cache_dir = "/tmp/nova-mypy-cache"
        base_argv = build_argv(tool, paths, project, cache_dir)
        if settings.use_host_executor:
            argv = resolve_host_argv(tool, root, base_argv)
            result = await _run_host(
                tool, argv, root=root, timeout=timeout, ctx=ctx
            )
        else:
            result = await _run_sandbox(
                tool,
                base_argv,
                root=root,
                repo_id=str(repo_id),
                timeout=timeout,
                ctx=ctx,
            )
    finally:
        if host_tmp:
            shutil.rmtree(host_tmp, ignore_errors=True)

    stdout = str(result.get("stdout") or "")
    stderr = str(result.get("stderr") or "")
    combined = f"{stdout}\n{stderr}".strip()
    if result.get("timed_out"):
        raise ToolBusinessError(
            f"{tool} 诊断超时（{timeout} 秒）：请缩小 paths 范围后重试"
        )
    if result.get("kill_failed"):
        raise ToolBusinessError(
            f"{tool} 诊断超时后未能结束进程，请手动检查残留进程"
        )

    exit_code = int(result.get("exit_code") or 0)
    diagnostics, parse_errors = _PARSERS[tool](stdout, root)
    if not diagnostics and stderr.strip():
        alt, alt_errors = _PARSERS[tool](stderr, root)
        diagnostics = alt
        parse_errors += alt_errors
    if exit_code not in _OK_EXIT_CODES[tool] and not diagnostics:
        detail = tail_text(combined or "(无输出)", 800)
        raise ToolBusinessError(
            f"无法运行 {tool} 诊断（exit={exit_code}）：{detail}"
        )

    ordered = sort_diagnostics(diagnostics)
    truncated = len(ordered) > max_results
    await log_audit(
        AuditAction.TOOL_CALL,
        user_id=str(ctx.user.get("id", "")) if ctx.user else "anonymous",
        details={
            "tool": TOOL_NAME,
            "runner": tool,
            "executor": result.get("executor"),
            "exit_code": exit_code,
            "timed_out": bool(result.get("timed_out")),
            "diagnostic_count": len(ordered),
            "truncated": truncated,
        },
    )
    return {
        "tool": tool,
        "runner": {
            "name": tool,
            "version": result.get("version"),
            "executor": result.get("executor"),
        },
        "command": result.get("command"),
        "ok": True,
        "exit_code": exit_code,
        "timed_out": False,
        "duration_ms": int(result.get("duration_ms") or 0),
        "diagnostics": ordered[:max_results],
        "summary": summarize(ordered),
        "truncated": truncated,
        "parse_errors": parse_errors,
        "raw_tail": tail_text(combined) if parse_errors else "",
        "warning": result.get("warning") if settings.use_host_executor else None,
    }


TOOL = ToolDefinition(
    name=TOOL_NAME,
    description=(
        "对已关联仓库运行固定版本的静态检查，返回结构化诊断"
        "（文件/行/列/级别/规则码/消息）。"
        "tool: ruff（Python lint）| mypy（Python 类型）| tsc（TypeScript 类型）。"
        "paths 为仓库内相对路径（最多 20 个，默认整个仓库）；"
        "tsc 用 project 指定仓库内 tsconfig（默认根 tsconfig.json），"
        "paths 对 tsc 不生效。只读，不修改仓库；"
        "本地模式没有容器隔离，会先请求审批。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "tool": {"type": "string"},
            "repo_id": {"type": "string"},
            "paths": {"type": "array", "items": {"type": "string"}},
            "project": {"type": "string"},
            "max_results": {"type": "integer"},
            "timeout": {"type": "integer"},
        },
        "required": ["tool"],
    },
    func=run_diagnostics,
    timeout=TOOL_TIMEOUT,
    category="read",
    capabilities=["fs.read"],
    parallel_safe=True,
)

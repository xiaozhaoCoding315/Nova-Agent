"""diagnostics tool: fixed-argv ruff / mypy / tsc with structured output.

The model chooses the runner, an optional repo and target paths; it cannot
inject flags or executables.  Server mode runs in the builder/node sandbox on
a sanitized copy; local mode runs the resolved host binary with shell=False
and marks the result as having no container isolation.
"""
import re
import shlex
import shutil
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
from app.core.security.paths import is_secret_path
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
# Diagnostics JSON can be much larger than ordinary command output; host runs
# get a higher cap so a big ruff report stays parseable.
HOST_OUTPUT_LIMIT = 2_000_000
# sandbox.runtime truncates stdout to 100_000 characters with no flag.
SANDBOX_STDOUT_LIMIT = 100_000
OUTPUT_TRUNCATED_WARNING = "输出过长已截断，诊断可能不完整"

_TOOL_SPECS = {
    "ruff": {"version": "0.8.6"},
    "mypy": {"version": "1.13.0"},
    "tsc": {"version": "5.6.3"},
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
        # Never pass --incremental false: composite projects reject it with
        # TS6379.  --tsBuildInfoFile is inert for non-composite projects and
        # redirects the composite build info into the throwaway cache dir.
        return [
            "tsc", "--noEmit", "--pretty", "false",
            "--tsBuildInfoFile", f"{cache_dir}/tsconfig.tsbuildinfo",
            "-p", project,
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


def _validate_paths(args: dict, root: Path) -> list[str]:
    raw = args.get("paths") or []
    if not isinstance(raw, list) or len(raw) > MAX_PATHS:
        raise ToolBusinessError(f"paths 必须是最多 {MAX_PATHS} 项的数组")
    paths: list[str] = []
    for item in raw:
        text = str(item or "").strip().replace("\\", "/")
        if not text:
            raise ToolBusinessError("paths 不能包含空路径")
        if text.startswith(("-", "@")):
            raise ToolBusinessError(f"paths 不能以 - 或 @ 开头：{item}")
        if "\n" in text or "\r" in text or "\x00" in text:
            raise ToolBusinessError(f"paths 不能包含换行或 NUL：{item}")
        if text.startswith("/") or re.match(r"^[A-Za-z]:", text):
            raise ToolBusinessError(f"paths 必须是仓库内相对路径：{item}")
        if any(part == ".." for part in text.split("/")):
            # Even ``sub/../file.py`` (which resolves inside the repo) is
            # rejected: the spec allows no traversal segments at all.
            raise ToolBusinessError(f"paths 不能包含 .. 路径段：{item}")
        candidate = (root / text).resolve(strict=False)
        if candidate != root and root not in candidate.parents:
            raise ToolBusinessError(f"paths 越出仓库目录：{item}")
        rel = candidate.relative_to(root).as_posix()
        if rel not in (".", "") and is_secret_path(rel):
            # Local mode reads the real repository; .env and key files must
            # never reach a runner whose output the model can read.
            raise ToolBusinessError(f"不能对密钥/凭据文件运行诊断：{rel}")
        paths.append(text)
    return paths


def _tsc_project(args: dict, root: Path) -> str:
    raw = str(args.get("project") or "tsconfig.json").strip().replace(
        "\\", "/"
    )
    if raw.startswith(("-", "@")):
        raise ToolBusinessError("project 不能以 - 或 @ 开头")
    if "\n" in raw or "\r" in raw or "\x00" in raw:
        raise ToolBusinessError("project 不能包含换行或 NUL")
    if raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
        raise ToolBusinessError("project 必须是仓库内相对路径")
    if any(part == ".." for part in raw.split("/")):
        raise ToolBusinessError("project 不能包含 .. 路径段")
    candidate = (root / raw).resolve(strict=False)
    if candidate != root and root not in candidate.parents:
        raise ToolBusinessError("project 越出仓库目录")
    rel = candidate.relative_to(root).as_posix()
    if rel not in (".", "") and is_secret_path(rel):
        raise ToolBusinessError(f"不能对密钥/凭据文件运行诊断：{rel}")
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
    attempted: dict | None = None,
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
    command = shlex.join(argv)
    started = time.perf_counter()
    if attempted is not None:
        # Mark before the call so a failed/cancelled run is audited too.
        attempted["started"] = True
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
    result["duration_ms"] = int((time.perf_counter() - started) * 1000)
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
        output_limit=HOST_OUTPUT_LIMIT,
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
    result: dict = {}
    ordered: list[dict] = []
    truncated = False
    exit_code: int | None = None
    sandbox_state: dict = {}
    try:
        if settings.use_host_executor and tool in ("mypy", "tsc"):
            host_tmp = tempfile.mkdtemp(prefix=f"nova-{tool}-")
            cache_dir = host_tmp
        elif tool == "mypy":
            cache_dir = "/tmp/nova-mypy-cache"
        elif tool == "tsc":
            # tsc writes the build-info file itself and does not create the
            # parent directory, so point it at the existing /tmp (the sandbox
            # workspace is a throwaway copy anyway; /tmp is never the repo).
            cache_dir = "/tmp"
        else:
            cache_dir = ""
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
                attempted=sandbox_state,
            )

        stdout = str(result.get("stdout") or "")
        stderr = str(result.get("stderr") or "")
        combined = f"{stdout}\n{stderr}".strip()
        raw_exit = result.get("exit_code")
        if isinstance(raw_exit, int) and not isinstance(raw_exit, bool):
            exit_code = raw_exit
        if result.get("kill_failed"):
            raise ToolBusinessError(
                f"{tool} 诊断超时后未能结束进程，请手动检查残留进程"
            )
        if result.get("timed_out"):
            raise ToolBusinessError(
                f"{tool} 诊断超时（{timeout} 秒）：请缩小 paths 范围后重试"
            )

        code = exit_code if exit_code is not None else 0
        diagnostics, parse_errors = _PARSERS[tool](stdout, root)
        if not diagnostics and stderr.strip():
            alt, alt_errors = _PARSERS[tool](stderr, root)
            diagnostics = alt
            parse_errors += alt_errors
        if code not in _OK_EXIT_CODES[tool] and not diagnostics:
            detail = tail_text(combined or "(无输出)", 800)
            raise ToolBusinessError(
                f"无法运行 {tool} 诊断（exit={code}）：{detail}"
            )

        ordered = sort_diagnostics(diagnostics)
        # The sandbox runtime caps stdout at 100_000 characters without a
        # truncation flag; treat a full buffer as truncated.
        output_truncated = bool(
            result.get("output_truncated") or result.get("stdout_truncated")
        )
        if (
            result.get("executor") == "sandbox"
            and len(stdout) >= SANDBOX_STDOUT_LIMIT
        ):
            output_truncated = True
        truncated = len(ordered) > max_results or output_truncated

        warnings: list[str] = []
        if settings.use_host_executor and result.get("warning"):
            warnings.append(str(result["warning"]))
        if output_truncated:
            warnings.append(OUTPUT_TRUNCATED_WARNING)

        if result.get("executor") != "sandbox":
            # Host mode keeps the ordinary tool_call entry; sandbox runs are
            # audited once in the finally block below so failures count too.
            await log_audit(
                AuditAction.TOOL_CALL,
                user_id=str(ctx.user.get("id", "")) if ctx.user else "anonymous",
                details={
                    "tool": TOOL_NAME,
                    "runner": tool,
                    "executor": result.get("executor"),
                    "exit_code": code,
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
            "exit_code": code,
            "timed_out": False,
            "duration_ms": int(result.get("duration_ms") or 0),
            "diagnostics": ordered[:max_results],
            "summary": summarize(ordered),
            "truncated": truncated,
            "parse_errors": parse_errors,
            "raw_tail": tail_text(combined) if parse_errors else "",
            "warning": "；".join(warnings) if warnings else None,
        }
    finally:
        if host_tmp:
            shutil.rmtree(host_tmp, ignore_errors=True)
        if sandbox_state.get("started"):
            # Sandbox quota counts sandbox_run rows: every attempted run must
            # produce exactly one, including timeouts and runner failures.
            await log_audit(
                AuditAction.SANDBOX_RUN,
                user_id=str(ctx.user.get("id", "")) if ctx.user else "anonymous",
                details={
                    "tool": TOOL_NAME,
                    "runner": tool,
                    "executor": result.get("executor") or "sandbox",
                    "exit_code": exit_code,
                    "timed_out": bool(result.get("timed_out")),
                    "diagnostic_count": len(ordered),
                    "truncated": truncated,
                },
            )


TOOL = ToolDefinition(
    name=TOOL_NAME,
    description=(
        "对已关联仓库运行固定版本的静态检查，返回结构化诊断"
        "（文件/行/列/级别/规则码/消息）。"
        "tool: ruff（Python lint）| mypy（Python 类型）| tsc（TypeScript 类型）。"
        "paths 为仓库内相对路径（最多 20 个，默认整个仓库）；"
        "tsc 用 project 指定仓库内 tsconfig（默认根 tsconfig.json），"
        "paths 对 tsc 不生效。只读，不修改仓库；"
        "本地 readonly 模式不提供此工具，ask 模式需审批，"
        "auto/full 直接运行但无容器隔离。"
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

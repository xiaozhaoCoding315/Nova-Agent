"""Tool-facing host execution helpers.

Wraps Task 7's executor for the tool layer: uniform no-isolation marking,
the mandated Chinese warning, multi-line command rejection (``cmd.exe``
silently truncates at embedded newlines) and business-error mapping so the
model never sees a stack trace.  Environment variables are never taken from
model-controlled tool arguments — only callers' hard-coded defaults may set
``env`` (e.g. a project venv PATH).
"""
import shutil
import uuid
from pathlib import Path

from app.config import settings
from app.core.exec.host import execute_host
from app.core.security.paths import is_secret_path, try_normalize_relpath
from app.core.tools.base import ToolBusinessError

WARNING = "本地执行无容器隔离：命令以当前 Windows 用户权限在你的项目目录运行"
KILL_WARNING = "（警告：命令超时后未能完全结束其进程，请手动检查残留进程）"


def _no_multiline(command: str) -> str:
    """Reject embedded newlines: cmd.exe truncates them silently."""
    text = str(command or "")
    if "\n" in text or "\r" in text:
        raise ToolBusinessError(
            "command 不能包含换行：cmd.exe 会静默截断多行命令；请拆分为单行命令后重试"
        )
    return text


def _with_warnings(result: dict) -> dict:
    warning = WARNING
    if result.get("kill_failed"):
        warning += KILL_WARNING
    result["warning"] = warning
    return result


async def run_command_host(
    command: str,
    *,
    root: str | Path,
    timeout: int,
    on_output=None,
    job_id: str | None = None,
    user_id=None,
) -> dict:
    _no_multiline(command)
    try:
        result = await execute_host(
            command,
            root=root,
            timeout=timeout,
            on_output=on_output,
            job_id=job_id,
            user_id=user_id,
        )
    except (ValueError, OSError) as exc:
        # resolve_cwd / Popen failures: business errors, not stack traces.
        raise ToolBusinessError(f"本地执行失败：{exc}") from exc
    _with_warnings(result)
    result["persisted"] = True
    result["isolated"] = False
    return result


def _safe_files(files: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw_path, content in (files or {}).items():
        rel = try_normalize_relpath(str(raw_path))
        if not rel or is_secret_path(rel):
            continue
        if not isinstance(content, str):
            continue
        out[rel] = content
    return out


async def run_code_host(
    files: dict,
    command: str | None,
    *,
    root: str | Path,
    timeout: int = 120,
    env: dict[str, str] | None = None,
    on_output=None,
    job_id: str | None = None,
    user_id=None,
) -> dict:
    """Run model-authored files in a throwaway directory on the host.

    ``env`` is a caller-side, code-approved value only.  The tool layer
    always passes ``None``; nothing derived from model tool arguments ever
    reaches the child environment (``execute_host`` would scrub it anyway).
    """
    payload = _safe_files(files)
    command = _no_multiline(command or "python main.py")
    base = settings.local_tmp_root / f"run-{uuid.uuid4().hex}"
    base.mkdir(parents=True, exist_ok=False)
    try:
        for rel, content in payload.items():
            target = base / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        try:
            result = await execute_host(
                command or "python main.py",
                root=base,
                timeout=timeout,
                env=env,
                on_output=on_output,
                job_id=job_id,
                user_id=user_id,
                venv_root=root,
            )
        except (ValueError, OSError) as exc:
            raise ToolBusinessError(f"本地执行失败：{exc}") from exc
        _with_warnings(result)
        result["workspace"] = "temporary"
        return result
    finally:
        shutil.rmtree(base, ignore_errors=True)

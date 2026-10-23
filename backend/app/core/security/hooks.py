"""Pre/post tool hooks.

Hook commands are configured by the operator (never by the model).  A hook
receives a JSON payload on stdin.  Exit code 2 blocks a pre-tool action and
returns stderr to the Agent; any non-zero pre-hook exit is treated as a
failure (fail closed).  Post-hook failures are logged but never change the
tool result.
"""
import asyncio
import json
import os
import shlex
import subprocess
from dataclasses import dataclass

import structlog

from app.core.security.redaction import redact_text

logger = structlog.get_logger()

HOOK_TIMEOUT_S = 10


@dataclass(frozen=True)
class HookResult:
    allowed: bool
    detail: str


def _split_command(command: str) -> list[str]:
    if os.name == "nt":
        tokens = shlex.split(command, posix=False)
        return [
            token[1:-1]
            if len(token) >= 2 and token[0] == token[-1] and token[0] in "\"'"
            else token
            for token in tokens
        ]
    return shlex.split(command)


async def run_hook(command: str, payload: dict, cwd: str | None = None) -> HookResult:
    if not (command or "").strip():
        return HookResult(True, "")
    try:
        argv = _split_command(command)
    except ValueError as exc:
        return HookResult(False, f"hook 配置无效：{exc}")
    if not argv:
        return HookResult(True, "")

    env = {
        **os.environ,
        "NOVA_HOOK_PHASE": str(payload.get("phase") or ""),
        "NOVA_TOOL": str(payload.get("tool") or ""),
    }

    def _run() -> subprocess.CompletedProcess:
        return subprocess.run(
            argv,
            input=json.dumps(payload, ensure_ascii=False),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=HOOK_TIMEOUT_S,
            cwd=cwd or None,
            env=env,
        )

    try:
        result = await asyncio.to_thread(_run)
    except FileNotFoundError:
        return HookResult(False, f"hook 命令不存在：{argv[0]}")
    except subprocess.TimeoutExpired:
        return HookResult(False, f"hook 超时（>{HOOK_TIMEOUT_S}s）")
    except Exception as exc:  # noqa: BLE001
        logger.warning("hook_execution_failed", error=str(exc))
        return HookResult(False, f"hook 执行失败：{exc}")

    stdout = redact_text(result.stdout or "")
    stderr = redact_text(result.stderr or "")
    detail = (stderr or stdout).strip()[:2000]
    if result.returncode == 0:
        return HookResult(True, stdout.strip()[:2000])
    if result.returncode == 2:
        return HookResult(False, detail or "blocked by hook")
    return HookResult(False, f"hook 退出码 {result.returncode}：{detail or 'no output'}")

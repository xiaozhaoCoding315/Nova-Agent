"""Run the verification profile for one repo inside the builder sandbox."""
import time
from datetime import datetime, timezone

import structlog

from app.config import settings
from app.core.sandbox.runtime import deps_volume_name, execute as sandbox_execute, sandbox_status
from app.core.tools.run_code import _collect_repo_files
from app.core.verify.profiles import detect_profile

logger = structlog.get_logger()


def _tail(text: str | None, limit: int) -> str:
    return (text or "")[-limit:]


async def run_verification(repo: dict, user: dict) -> dict:
    started = time.perf_counter()
    files = await _collect_repo_files(str(repo["id"]), user)
    profile = detect_profile(files)
    now = datetime.now(timezone.utc).isoformat()

    if not profile.steps:
        return {
            "status": "unsupported",
            "stack": profile.stack,
            "notes": profile.notes + ([profile.unsupported_reason] if profile.unsupported_reason else []),
            "steps": [],
            "exit_code": -1,
            "stdout": "",
            "stderr": profile.unsupported_reason,
            "command": "",
            "image": "",
            "at": now,
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
        }

    status = await sandbox_status()
    if not status["available"]:
        return {
            "status": "failed",
            "stack": profile.stack,
            "notes": profile.notes,
            "steps": [],
            "exit_code": -1,
            "stdout": "",
            "stderr": f"沙箱不可用：{status['reason']}",
            "command": "",
            "image": "",
            "at": now,
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
        }

    image = settings.sandbox_builder_image if status.get("builder_available") else settings.sandbox_image
    notes = list(profile.notes)
    if not status.get("builder_available"):
        notes.append("builder 镜像不可用，已退回 slim 镜像；依赖可能不完整")

    steps: list[dict] = []
    stopped_early = False
    for index, step in enumerate(profile.steps):
        step_started = time.perf_counter()
        result = await sandbox_execute(
            files=files,
            command=step.command,
            timeout=step.timeout,
            image=image,
            deps_volume=deps_volume_name(str(repo["id"])),
        )
        exit_code = result.get("exit_code", -1)
        timed_out = bool(result.get("timed_out"))
        if timed_out:
            step_status = "failed"
        elif exit_code == 127 and not step.required:
            step_status = "skipped"
        elif exit_code == 0:
            step_status = "passed"
        else:
            step_status = "failed"

        steps.append({
            "name": step.name,
            "command": step.command,
            "required": step.required,
            "status": step_status,
            "exit_code": exit_code,
            "timed_out": timed_out,
            "stdout": _tail(result.get("stdout"), 4000),
            "stderr": _tail(result.get("stderr"), 1500),
            "duration_ms": int((time.perf_counter() - step_started) * 1000),
        })

        if step_status == "failed" and not step.required:
            notes.append(f"「{step.name}」失败（非必需步骤，不阻断通过）")
        if step_status == "failed" and step.required:
            if index < len(profile.steps) - 1:
                notes.append(f"「{step.name}」失败，后续检查已跳过")
            stopped_early = True
            break

    required = [s for s in steps if s["required"]]
    failed = [s for s in required if s["status"] == "failed"]
    passed = [s for s in steps if s["status"] == "passed"]
    overall = "failed" if failed else "passed" if passed else "unsupported"
    if stopped_early:
        overall = "failed"

    first_failure = next(
        (s for s in steps if s["status"] == "failed" and s["required"]), None
    )
    stdout = "\n\n".join(
        f"$ {s['command']}\n{s['stdout']}" for s in steps if s["stdout"]
    )
    stderr = "\n\n".join(
        f"$ {s['command']}\n{s['stderr']}" for s in steps if s["stderr"]
    )

    logger.info(
        "verification_done",
        repo_id=str(repo["id"]), stack=profile.stack,
        status=overall, steps=len(steps),
    )
    return {
        "status": overall,
        "stack": profile.stack,
        "notes": notes,
        "steps": steps,
        "exit_code": first_failure["exit_code"] if first_failure else 0,
        "stdout": stdout[-6000:],
        "stderr": stderr[-3000:],
        "command": " → ".join(step.command for step in profile.steps),
        "image": image,
        "at": now,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
    }

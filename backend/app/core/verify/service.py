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


async def run_verification(
    repo: dict, user: dict, overrides: dict[str, str] | None = None
) -> dict:
    started = time.perf_counter()
    files = await _collect_repo_files(str(repo["id"]), user)
    if overrides:
        # Gate runs before the proposal is written to disk.
        files.update({str(k): str(v) for k, v in overrides.items()})
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
    needs_builder = any(step.image != "node" for step in profile.steps)
    if needs_builder and not status["available"]:
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

    allow_network = settings.sandbox_allow_network and user.get("role") == "admin"
    notes = list(profile.notes)
    if needs_builder and not status.get("builder_available"):
        notes.append("builder 镜像不可用，Python 步骤将退回 slim 镜像；依赖可能不完整")
    if any(step.image == "node" for step in profile.steps) and not status.get("node_available"):
        notes.append("node 镜像不可用，Node 步骤会明确失败或跳过")

    steps: list[dict] = []
    images_used: set[str] = set()
    stopped_early = False
    for index, step in enumerate(profile.steps):
        step_started = time.perf_counter()
        step_status = "failed"
        exit_code = -1
        timed_out = False
        result: dict = {}
        if step.image == "node" and not status.get("node_available"):
            step_status = "failed" if step.required else "skipped"
            result = {
                "stdout": "",
                "stderr": f"node 镜像未就绪：请构建 {settings.sandbox_node_image}",
                "exit_code": -1,
                "timed_out": False,
            }
        else:
            if step.image == "node":
                image = settings.sandbox_node_image
                volume = deps_volume_name(str(repo["id"]), "node")
                mount = "/workspace/node_modules"
                images_used.add("node")
            else:
                image = (
                    settings.sandbox_builder_image
                    if status.get("builder_available")
                    else settings.sandbox_image
                )
                volume = deps_volume_name(str(repo["id"]))
                mount = None
                images_used.add("builder" if status.get("builder_available") else "slim")

            network = bool(step.network and allow_network)
            if step.network and not allow_network:
                notes.append(f"「{step.name}」需要联网，但当前账号/配置不允许；依赖未缓存时会失败")
            result = await sandbox_execute(
                files=files,
                command=step.command,
                timeout=step.timeout,
                image=image,
                deps_volume=volume,
                deps_mount=mount,
                network=network,
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
    resolved_image = "mixed" if len(images_used) > 1 else (
        next(iter(images_used)) if images_used else ""
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
        "image": resolved_image,
        "at": now,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
    }

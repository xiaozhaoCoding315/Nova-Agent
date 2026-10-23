"""Docker-only sandbox for executing LLM-authored code.

Security invariants (do not weaken):
- There is NO fallback to host execution. If Docker is unavailable the
  caller must report the tool as unavailable instead.
- Containers run with no network, read-only root, all capabilities dropped,
  a non-root uid, pid/memory/cpu limits, and an explicit ``--name`` so that
  timeouts can reliably kill the exact container.
"""
import asyncio
import re
import shutil
import tempfile
import uuid

import structlog

from app.config import settings

logger = structlog.get_logger()

_docker_checked: bool | None = None

_SAFE_PATH = re.compile(r"^[\w./\-]+$")


def is_docker_available() -> bool:
    global _docker_checked
    if _docker_checked is None:
        if shutil.which("docker") is None:
            _docker_checked = False
        else:
            import subprocess
            try:
                result = subprocess.run(["docker", "info"], capture_output=True, timeout=5)
                _docker_checked = result.returncode == 0
            except Exception:  # noqa: BLE001
                _docker_checked = False
    return _docker_checked


async def sandbox_status() -> dict:
    """Report availability honestly — never silently degrade."""
    if not settings.sandbox_enabled:
        return {"available": False, "reason": "disabled by config"}

    docker_ok = await asyncio.to_thread(is_docker_available)
    if not docker_ok:
        return {"available": False, "reason": "docker daemon not reachable"}

    def _image_exists() -> bool:
        import subprocess
        result = subprocess.run(
            ["docker", "image", "inspect", settings.sandbox_image],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0

    try:
        has_image = await asyncio.to_thread(_image_exists)
    except Exception:  # noqa: BLE001
        has_image = False

    if not has_image:
        return {
            "available": False,
            "reason": f"sandbox image missing — build it: docker build -f Dockerfile.sandbox -t {settings.sandbox_image} .",
        }
    return {"available": True, "image": settings.sandbox_image}


def _safe_relpath(path: str) -> str:
    """Reject absolute paths and traversal so uploaded files stay in workdir."""
    path = path.replace("\\", "/").lstrip("/")
    if not path or ".." in path.split("/") or not _SAFE_PATH.match(path):
        raise ValueError(f"unsafe file path: {path!r}")
    return path


async def execute(
    files: dict[str, str],
    command: str | None = None,
    stdin: str = "",
    timeout: int | None = None,
) -> dict:
    """Run ``files`` in the sandbox container.

    Returns {"stdout", "stderr", "exit_code", "timed_out", "sandboxed", "command"}.
    ``sandboxed`` is always True here — kept in the payload for auditability.
    """
    timeout = timeout or settings.sandbox_timeout
    status = await sandbox_status()
    if not status["available"]:
        return {
            "stdout": "",
            "stderr": f"沙箱不可用：{status['reason']}",
            "exit_code": -1,
            "timed_out": False,
            "sandboxed": False,
            "command": "",
        }

    if not files:
        return {
            "stdout": "", "stderr": "no files provided", "exit_code": -1,
            "timed_out": False, "sandboxed": False, "command": "",
        }
    if len(files) > 20 or any(len(v) > 200_000 for v in files.values()):
        return {
            "stdout": "", "stderr": "too many files or file too large (max 20 files / 200KB each)",
            "exit_code": -1, "timed_out": False, "sandboxed": False, "command": "",
        }

    command = command or "python main.py"
    container_name = f"nova-sbx-{uuid.uuid4().hex[:12]}"
    tmp_dir = None
    try:
        tmp_dir = tempfile.mkdtemp(prefix="nova_sandbox_")
        for relpath, content in files.items():
            rel = _safe_relpath(relpath)
            target = f"{tmp_dir}/{rel}"
            import os
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "w", encoding="utf-8") as fh:
                fh.write(content)

        # `timeout` inside the container is the first line of defense;
        # the outer asyncio timeout + docker kill is the backstop.
        inner = f"timeout {timeout}s sh -c {_shell_quote(command)}"

        cmd = [
            "docker", "run", "--rm",
            "--name", container_name,
            "--network", "none",
            "--read-only",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--pids-limit", "64",
            "--memory", settings.sandbox_memory,
            "--cpus", settings.sandbox_cpus,
            "--tmpfs", "/tmp:rw,size=64m",
            "--user", "65534:65534",
            "-v", f"{tmp_dir}:/workspace:rw",
            "-w", "/workspace",
            settings.sandbox_image,
            "sh", "-c", inner,
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.PIPE if stdin else asyncio.subprocess.DEVNULL,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=stdin.encode() if stdin else None),
                timeout=timeout + 10,  # docker startup overhead buffer
            )
            return {
                "stdout": stdout.decode("utf-8", errors="replace")[:100_000],
                "stderr": stderr.decode("utf-8", errors="replace")[:10_000],
                "exit_code": proc.returncode,
                "timed_out": False,
                "sandboxed": True,
                "command": command,
            }
        except asyncio.TimeoutError:
            # Kill by the exact container name — the name is real this time.
            for kill_cmd in (["docker", "kill", container_name],
                             ["docker", "rm", "-f", container_name]):
                try:
                    killer = await asyncio.create_subprocess_exec(
                        *kill_cmd,
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.DEVNULL,
                    )
                    await asyncio.wait_for(killer.wait(), timeout=10)
                except Exception:  # noqa: BLE001
                    pass
            return {
                "stdout": "", "stderr": f"execution timed out after {timeout}s",
                "exit_code": -1, "timed_out": True, "sandboxed": True, "command": command,
            }
    except Exception as exc:  # noqa: BLE001
        logger.error("sandbox_execution_failed", error=str(exc))
        return {
            "stdout": "", "stderr": f"sandbox error: {exc}", "exit_code": -1,
            "timed_out": False, "sandboxed": True, "command": command,
        }
    finally:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)


def _shell_quote(s: str) -> str:
    return "'" + s.replace("'", "'\"'\"'") + "'"
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
import subprocess
import tempfile
import time
import uuid

import structlog

from app.config import settings

logger = structlog.get_logger()

_docker_checked: bool | None = None
_docker_checked_at: float = 0.0
_DOCKER_NEGATIVE_TTL_S = 30

_SAFE_PATH = re.compile(r"^[\w./\-]+$")


def is_docker_available() -> bool:
    """Docker probe. Positive results are cached; negatives expire after 30s
    so starting Docker Desktop does not require a server restart."""
    global _docker_checked, _docker_checked_at
    now = time.time()
    if _docker_checked and _docker_checked_at:
        return True
    if _docker_checked is False and now - _docker_checked_at < _DOCKER_NEGATIVE_TTL_S:
        return False

    if shutil.which("docker") is None:
        _docker_checked, _docker_checked_at = False, now
        return False
    import subprocess
    try:
        result = subprocess.run(["docker", "info"], capture_output=True, timeout=5)
        _docker_checked = result.returncode == 0
    except Exception:  # noqa: BLE001
        _docker_checked = False
    _docker_checked_at = now
    return bool(_docker_checked)


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
    if len(files) > 400 or any(len(v) > 200_000 for v in files.values()):
        return {
            "stdout": "", "stderr": "too many files or file too large (max 400 files / 200KB each)",
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

        proc_result = await asyncio.to_thread(
            _run_docker, cmd, stdin.encode("utf-8") if stdin else None, timeout + 10
        )
        return {
            "stdout": proc_result.stdout.decode("utf-8", errors="replace")[:100_000],
            "stderr": proc_result.stderr.decode("utf-8", errors="replace")[:10_000],
            "exit_code": proc_result.returncode,
            "timed_out": False,
            "sandboxed": True,
            "command": command,
        }
    except (subprocess.TimeoutExpired, TimeoutError):
        # `subprocess.run` timeout kills the docker CLI; the container itself
        # is stopped by its exact --name (the name is real this time).
        for kill_cmd in (["docker", "kill", container_name],
                         ["docker", "rm", "-f", container_name]):
            try:
                await asyncio.to_thread(
                    subprocess.run, kill_cmd, capture_output=True, timeout=15
                )
            except Exception:  # noqa: BLE001
                pass
        return {
            "stdout": "", "stderr": f"execution timed out after {timeout}s",
            "exit_code": -1, "timed_out": True, "sandboxed": True, "command": command,
        }
    except Exception as exc:  # noqa: BLE001
        logger.error("sandbox_execution_failed", error=str(exc), error_type=type(exc).__name__)
        return {
            "stdout": "", "stderr": f"sandbox error: {type(exc).__name__}: {exc}", "exit_code": -1,
            "timed_out": False, "sandboxed": True, "command": command,
        }
    finally:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)


def _run_docker(cmd: list[str], stdin_bytes: bytes | None, timeout: int) -> "subprocess.CompletedProcess":
    """Blocking docker invocation, executed in a worker thread.

    Deliberately not asyncio.create_subprocess_exec: on Windows the app uses
    SelectorEventLoop (psycopg), which does not support subprocesses.
    """
    return subprocess.run(
        cmd,
        input=stdin_bytes,
        capture_output=True,
        timeout=timeout,
    )


def _shell_quote(s: str) -> str:
    return "'" + s.replace("'", "'\"'\"'") + "'"
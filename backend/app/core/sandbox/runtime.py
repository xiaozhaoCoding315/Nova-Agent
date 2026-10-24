"""Docker-only sandbox for executing LLM-authored code.

Security invariants (do not weaken):
- There is NO fallback to host execution. If Docker is unavailable the
  caller must report the tool as unavailable instead.
- Containers run with no network, read-only root, all capabilities dropped,
  a non-root uid, pid/memory/cpu limits, and an explicit ``--name`` so that
  timeouts can reliably kill the exact container.
"""
import asyncio
import os
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

    def _image_exists(image: str) -> bool:
        import subprocess
        result = subprocess.run(
            ["docker", "image", "inspect", image],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0

    async def check(image: str) -> bool:
        try:
            return await asyncio.to_thread(_image_exists, image)
        except Exception:  # noqa: BLE001
            return False

    has_default = await check(settings.sandbox_image)
    has_builder = await check(settings.sandbox_builder_image)
    has_node = await check(settings.sandbox_node_image)

    if not has_default:
        return {
            "available": False,
            "reason": f"sandbox image missing — build it: docker build -f Dockerfile.sandbox -t {settings.sandbox_image} .",
            "builder_available": has_builder,
            "builder_image": settings.sandbox_builder_image,
            "node_available": has_node,
            "node_image": settings.sandbox_node_image,
            "network_enabled": settings.sandbox_allow_network,
        }
    return {
        "available": True,
        "image": settings.sandbox_image,
        "builder_available": has_builder,
        "builder_image": settings.sandbox_builder_image,
        "node_available": has_node,
        "node_image": settings.sandbox_node_image,
        "network_enabled": settings.sandbox_allow_network,
    }


def deps_volume_name(repo_id: str, kind: str = "python") -> str:
    """Per-repo named volume holding installed packages/node_modules."""
    safe = "".join(ch for ch in str(repo_id) if ch.isalnum() or ch in "-_")
    prefix = "nova-node-deps" if kind == "node" else "nova-deps"
    return f"{prefix}-{safe}"


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
    image: str | None = None,
    network: bool = False,
    deps_volume: str | None = None,
    deps_mount: str | None = None,
    as_root: bool = False,
    job_id: str | None = None,
    workspace_dir: str | None = None,
    user: str | None = None,
) -> dict:
    """Run ``files`` in the sandbox container.

    Returns {"stdout", "stderr", "exit_code", "timed_out", "sandboxed", "command"}.
    ``deps_volume`` mounts a per-repo named volume at /deps (PYTHONPATH) so
    packages installed with ``pip --target`` persist across runs.
    ``as_root`` is only used for the admin-only dependency installer.
    ``workspace_dir`` mounts an existing host directory at /workspace instead
    of copying ``files`` — container changes persist (used by run_command).
    ``user`` overrides the container uid:gid (needed when the mounted
    workspace belongs to another uid, e.g. the app account).
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

    if not files and not workspace_dir:
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
        if workspace_dir:
            tmp_dir = workspace_dir
        else:
            tmp_dir = tempfile.mkdtemp(prefix="nova_sandbox_")
        for relpath, content in files.items():
            rel = _safe_relpath(relpath)
            target = f"{tmp_dir}/{rel}"
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "w", encoding="utf-8") as fh:
                fh.write(content)
        if deps_volume and deps_mount and deps_mount.startswith("/workspace/"):
            os.makedirs(
                os.path.join(tmp_dir, deps_mount[len("/workspace/"):]),
                exist_ok=True,
            )

        # `timeout` inside the container is the first line of defense;
        # the outer subprocess timeout + docker kill is the backstop.
        inner = f"timeout {timeout}s sh -c {_shell_quote(command)}"

        extra: list[str] = []
        if deps_volume:
            mount = deps_mount or "/deps"
            mode = "rw" if as_root else "ro"
            extra += ["-v", f"{deps_volume}:{mount}:{mode}"]
            if mount == "/deps":
                extra += ["-e", "PYTHONPATH=/deps:/workspace"]
        if network:
            extra += ["-e", "PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple"]
            extra += ["-e", "PIP_DISABLE_PIP_VERSION_CHECK=1"]
            extra += ["-e", "npm_config_registry=https://registry.npmmirror.com"]
        if image == settings.sandbox_node_image:
            extra += ["-e", "npm_config_cache=/tmp/npm-cache"]
            extra += ["-e", "npm_config_update_notifier=false"]
        if as_root:
            extra += ["--user", "0:0"]
        elif user:
            extra += ["--user", user]
        else:
            extra += ["--user", "65534:65534"]

        labels = []
        if job_id:
            safe_job = "".join(ch for ch in str(job_id) if ch.isalnum() or ch in "-_")
            labels = ["--label", f"nova.job_id={safe_job}"]

        cmd = [
            "docker", "run", "--rm",
            "--name", container_name,
            *labels,
            "--network", "bridge" if network else "none",
            "--read-only",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--pids-limit", "64",
            "--memory", settings.sandbox_memory,
            "--cpus", settings.sandbox_cpus,
            "--tmpfs", "/tmp:rw,size=64m",
            *extra,
            "-v", f"{tmp_dir}:/workspace:rw",
            "-w", "/workspace",
            image or settings.sandbox_image,
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
        if tmp_dir and not workspace_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)


async def kill_job_containers(job_id: str) -> int:
    """Stop sandbox containers labelled with ``job_id``.

    Used by the job runner when a user cancels a long-running task.  The
    sandbox still has its own timeout as a backstop; this makes cancellation
    take effect immediately instead of waiting for the command to finish.
    """
    safe_job = "".join(ch for ch in str(job_id) if ch.isalnum() or ch in "-_")
    if not safe_job or shutil.which("docker") is None:
        return 0

    def _run() -> int:
        listed = subprocess.run(
            ["docker", "ps", "-q", "--filter", f"label=nova.job_id={safe_job}"],
            capture_output=True,
            timeout=15,
        )
        ids = [line.strip() for line in listed.stdout.decode("utf-8", "replace").splitlines() if line.strip()]
        killed = 0
        for container_id in ids:
            result = subprocess.run(
                ["docker", "kill", container_id],
                capture_output=True,
                timeout=15,
            )
            if result.returncode == 0:
                killed += 1
        return killed

    try:
        return await asyncio.to_thread(_run)
    except Exception as exc:  # noqa: BLE001
        logger.warning("sandbox_job_kill_failed", job_id=safe_job, error=str(exc))
        return 0


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
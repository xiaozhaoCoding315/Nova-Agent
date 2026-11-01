"""Docker-only sandbox for executing LLM-authored code.

Security invariants (do not weaken):
- There is NO fallback to host execution. If Docker is unavailable the
  caller must report the tool as unavailable instead.
- Containers run with no network, read-only root, all capabilities dropped,
  a non-root uid, pid/memory/cpu limits, and an explicit ``--name`` so that
  timeouts can reliably kill the exact container.
"""
import asyncio
import json
import os
import queue
import re
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Callable

import structlog

from app.config import settings
from app.core.security.paths import is_secret_path

logger = structlog.get_logger()

_docker_checked: bool | None = None
_docker_checked_at: float = 0.0
_DOCKER_NEGATIVE_TTL_S = 30

_SAFE_PATH = re.compile(r"^[\w./\-]+$")

# Heavy directories are skipped when building a sanitized copy: a read-only
# command does not need node_modules/.venv, and traversing them is expensive.
_SANITIZE_SKIP_DIRS = {
    "node_modules", ".venv", "venv", "__pycache__", "dist", "build", "out",
    ".next", ".nuxt", "target", "vendor", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", ".tox", "coverage", "site-packages",
}
_SANITIZE_MAX_FILES = 50_000
_MASK_MAX_ENTRIES = 200

_self_mounts_cache: dict[str, str] | None = None


def _in_container() -> bool:
    if Path("/.dockerenv").exists():
        return True
    try:
        cgroup = Path("/proc/self/cgroup").read_text(encoding="utf-8", errors="ignore")
        return "docker" in cgroup or "containerd" in cgroup
    except OSError:
        return False


def _self_mounts() -> dict[str, str]:
    """Map container mount destinations to host sources (empty when unknown).

    The app talks to the host Docker daemon.  Paths passed to ``docker run -v``
    are resolved on the **host**, so a container path such as ``/app/data/...``
    must be translated to the backing host mount (named volume or bind mount).
    """
    global _self_mounts_cache
    if _self_mounts_cache is not None:
        return _self_mounts_cache
    _self_mounts_cache = {}
    if not _in_container() or shutil.which("docker") is None:
        return _self_mounts_cache
    try:
        hostname = socket.gethostname()
        result = subprocess.run(
            ["docker", "inspect", hostname, "--format", "{{json .Mounts}}"],
            capture_output=True, timeout=5,
        )
        if result.returncode != 0:
            return _self_mounts_cache
        for mount in json.loads(result.stdout.decode("utf-8", "replace") or "[]"):
            destination = str(mount.get("Destination") or "").rstrip("/")
            source = str(mount.get("Source") or "").rstrip("/")
            if destination and source:
                _self_mounts_cache[destination or "/"] = source
    except Exception as exc:  # noqa: BLE001
        logger.warning("self_mount_inspect_failed", error=str(exc))
    return _self_mounts_cache


def _host_visible_path(path: str) -> str:
    """Translate an in-container data path to the host path Docker needs."""
    p = Path(path).resolve()
    explicit = (settings.sandbox_host_data_dir or "").strip()
    if explicit:
        container_root = Path(settings.user_data_dir).resolve().parent
        try:
            return str(Path(explicit) / p.relative_to(container_root))
        except ValueError:
            pass

    best: tuple[str, str, Path] | None = None
    for destination, source in _self_mounts().items():
        try:
            relative = p.relative_to(Path(destination))
        except ValueError:
            continue
        if best is None or len(str(destination)) > len(best[0]):
            best = (str(destination), source, relative)
    if best is None:
        return str(p)
    _, source, relative = best
    return str(Path(source) / relative) if str(relative) != "." else source


def _sandbox_tmp_root() -> str:
    """Temp files must live on a host-visible mount, not the container layer."""
    base = Path(settings.user_data_dir).resolve().parent / "sandbox_tmp"
    try:
        base.mkdir(parents=True, exist_ok=True)
        return str(base)
    except OSError:
        return tempfile.gettempdir()


def _build_secret_masks(root: str) -> tuple[list[tuple[str, str]], str | None]:
    """Create bind-mount masks that hide secret files from a rw workspace.

    Returns ``[(mask_source, workspace_relative_path)]`` plus the temp dir to
    clean up.  Secret directories are masked with an empty directory, secret
    files with an empty file; ``.git/config`` is replaced only when it embeds
    URL credentials.
    """
    base = Path(root)
    if not base.is_dir():
        return [], None
    mask_root = Path(tempfile.mkdtemp(prefix="nova_mask_", dir=_sandbox_tmp_root()))
    empty_file = mask_root / "empty"
    empty_file.write_bytes(b"")
    empty_dir = mask_root / "empty_dir"
    empty_dir.mkdir()
    masks: list[tuple[str, str]] = []
    seen: set[str] = set()

    def _add(rel: str, source: Path) -> None:
        if rel in seen or len(masks) >= _MASK_MAX_ENTRIES or ":" in rel:
            return
        seen.add(rel)
        masks.append((str(source), rel))

    for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
        rel_dir = Path(dirpath).relative_to(base).as_posix()
        keep: list[str] = []
        for name in dirnames:
            rel = name if rel_dir == "." else f"{rel_dir}/{name}"
            if name in _SANITIZE_SKIP_DIRS:
                continue
            if name == ".git":
                continue  # handled separately; don't mask the repo metadata
            if is_secret_path(rel):
                _add(rel, empty_dir)
                continue
            if os.path.islink(os.path.join(dirpath, name)):
                continue
            keep.append(name)
        dirnames[:] = keep
        for name in filenames:
            rel = name if rel_dir == "." else f"{rel_dir}/{name}"
            if is_secret_path(rel):
                _add(rel, empty_file)

    git_config = base / ".git" / "config"
    if git_config.is_file():
        try:
            text = git_config.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        if re.search(r"(https?://)[^/\s@]+@", text):
            scrubbed = re.sub(r"(https?://)[^/\s@]+@", r"\1***@", text)
            config_copy = mask_root / "git_config"
            config_copy.write_text(scrubbed, encoding="utf-8")
            _add(".git/config", config_copy)

    if len(masks) >= _MASK_MAX_ENTRIES:
        logger.warning("secret_masks_truncated", root=root, limit=_MASK_MAX_ENTRIES)
    return masks, str(mask_root)


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
    if settings.use_host_executor:
        # Local mode: the host executor is the runtime. Honest about what it
        # is (no container) so callers and the UI can show the warning.  The
        # image-availability flags become host-PATH probes; host tool branches
        # do not consult them, they exist for status/UI callers.
        python_available = bool(shutil.which("python") or shutil.which("python3"))
        node_available = shutil.which("node") is not None
        return {
            "available": True,
            "reason": "",
            "executor": "host",
            "isolation": "none",
            "docker": False,
            "default_available": python_available,
            # The builder image is intentionally blocked locally (host runs
            # use the host toolchain), so never advertise it as available.
            "builder_available": False,
            "node_available": node_available,
            "warning": "本地执行无容器隔离",
        }
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


def _scrub_git_config(config_path: Path) -> None:
    """Remove credentials embedded in remote URLs from a copied .git/config."""
    try:
        text = config_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    scrubbed = re.sub(r"(https?://)[^/\s@]+@", r"\1***@", text)
    if scrubbed != text:
        try:
            # Break the hardlink first: writing in place would also modify the
            # original repo's .git/config.
            config_path.unlink(missing_ok=True)
            config_path.write_text(scrubbed, encoding="utf-8")
        except OSError:
            pass


def _copy_sanitized_workspace(root: str, include_git: bool) -> str:
    """Hard-link a workspace copy without secret files.

    Used for read-only/ask shell commands so a classification miss cannot
    read credentials (a read-only bind mount still allows reads).  Heavy
    directories are skipped; ``.git`` is only copied for git commands and
    its config is scrubbed of embedded URL credentials.
    """
    src = Path(root)
    # Prefer the repo's filesystem so hardlinks work (the app's /tmp is often
    # a different volume from the repo data volume, which would force a full
    # content copy on every read-only command).
    try:
        dest = Path(tempfile.mkdtemp(prefix=".nova_ro_ws_", dir=str(src.parent)))
    except OSError:
        dest = Path(tempfile.mkdtemp(prefix="nova_ro_ws_"))
    copied = 0
    try:
        os.chmod(dest, 0o755)
    except OSError:
        pass

    for dirpath, dirnames, filenames in os.walk(src, followlinks=False):
        rel_dir = Path(dirpath).relative_to(src).as_posix()
        keep: list[str] = []
        for name in dirnames:
            rel = name if rel_dir == "." else f"{rel_dir}/{name}"
            if name in _SANITIZE_SKIP_DIRS:
                continue
            if name == ".git":
                if include_git:
                    keep.append(name)
                continue
            if is_secret_path(rel):
                continue
            if os.path.islink(os.path.join(dirpath, name)):
                continue
            keep.append(name)
        dirnames[:] = keep

        for name in filenames:
            rel = name if rel_dir == "." else f"{rel_dir}/{name}"
            if rel.startswith(".git/"):
                if not include_git:
                    continue
            elif is_secret_path(rel):
                continue
            source = os.path.join(dirpath, name)
            if os.path.islink(source):
                continue
            if copied >= _SANITIZE_MAX_FILES:
                logger.warning("sanitized_workspace_truncated", root=root,
                               limit=_SANITIZE_MAX_FILES)
                if include_git:
                    _scrub_git_config(dest / ".git" / "config")
                return str(dest)
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(source, target)
            except OSError:
                try:
                    shutil.copy2(source, target, follow_symlinks=False)
                except OSError:
                    continue
            copied += 1

    if include_git:
        _scrub_git_config(dest / ".git" / "config")
    return str(dest)


async def _kill_container(container_name: str) -> None:
    def _kill() -> None:
        for cmd in (["docker", "kill", container_name],
                    ["docker", "rm", "-f", container_name]):
            try:
                subprocess.run(cmd, capture_output=True, timeout=15)
            except Exception:  # noqa: BLE001
                pass

    try:
        # The task may already be cancelled; shield the cleanup so it still runs.
        await asyncio.shield(asyncio.to_thread(_kill))
    except Exception:  # noqa: BLE001
        pass


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
    sanitized_workspace: bool = False,
    include_git: bool = False,
    mask_secrets: bool = False,
    on_output: Callable[[str, str], None] | None = None,
    user_label: str | None = None,
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
    mask_tmp = None
    ephemeral_dir = False
    try:
        if workspace_dir and sanitized_workspace:
            tmp_dir = await asyncio.to_thread(
                _copy_sanitized_workspace, workspace_dir, include_git
            )
            ephemeral_dir = True
        elif workspace_dir:
            tmp_dir = workspace_dir
        else:
            tmp_dir = tempfile.mkdtemp(prefix="nova_sandbox_", dir=_sandbox_tmp_root())
            ephemeral_dir = True
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
        if workspace_dir and sanitized_workspace:
            # Sanitized copies are hardlinked; read-only mount prevents a
            # command from writing through a link into the real repo.
            extra += ["-e", "GIT_OPTIONAL_LOCKS=0"]
        mask_args: list[str] = []
        if workspace_dir and mask_secrets and not sanitized_workspace:
            masks, mask_tmp = await asyncio.to_thread(_build_secret_masks, workspace_dir)
            for source, rel in masks:
                mask_args += ["-v", f"{_host_visible_path(source)}:/workspace/{rel}:ro"]

        labels = []
        if job_id:
            safe_job = "".join(ch for ch in str(job_id) if ch.isalnum() or ch in "-_")
            labels += ["--label", f"nova.job_id={safe_job}"]
        if user_label:
            safe_user = "".join(ch for ch in str(user_label) if ch.isalnum() or ch in "-_")
            labels += ["--label", f"nova.user_id={safe_user}"]

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
            "-v", f"{_host_visible_path(str(tmp_dir))}:/workspace:"
                  f"{'ro' if workspace_dir and sanitized_workspace else 'rw'}",
            *mask_args,
            "-w", "/workspace",
            image or settings.sandbox_image,
            "sh", "-c", inner,
        ]

        stream_timed_out = False
        try:
            if on_output is not None:
                proc_result, stream_timed_out = await asyncio.to_thread(
                    _run_docker_streaming,
                    cmd,
                    stdin.encode("utf-8") if stdin else None,
                    timeout, on_output,
                )
                if stream_timed_out:
                    await _kill_container(container_name)
            else:
                proc_result = await asyncio.to_thread(
                    _run_docker, cmd, stdin.encode("utf-8") if stdin else None, timeout + 10
                )
        except asyncio.CancelledError:
            # Stop button: the worker thread cannot be interrupted, so kill the
            # exact container instead of letting it run until its own timeout.
            await _kill_container(container_name)
            raise
        return {
            "stdout": proc_result.stdout.decode("utf-8", errors="replace")[:100_000],
            "stderr": proc_result.stderr.decode("utf-8", errors="replace")[:10_000],
            "exit_code": proc_result.returncode,
            "timed_out": stream_timed_out,
            "sandboxed": True,
            "command": command,
        }
    except (subprocess.TimeoutExpired, TimeoutError):
        # `subprocess.run` timeout kills the docker CLI; the container itself
        # is stopped by its exact --name (the name is real this time).
        await _kill_container(container_name)
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
        if tmp_dir and ephemeral_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        if mask_tmp:
            shutil.rmtree(mask_tmp, ignore_errors=True)


async def kill_job_containers(job_id: str, user_id: int | str | None = None) -> int:
    """Stop sandbox containers labelled with ``job_id`` (optionally per user).

    Used by the job runner when a user cancels a long-running task, and by the
    chat tool-cancel endpoint.  The sandbox still has its own timeout as a
    backstop; this makes cancellation take effect immediately.
    """
    if settings.is_local:
        from app.core.exec.host import cancel_host_processes
        return await cancel_host_processes(job_id, user_id)
    safe_job = "".join(ch for ch in str(job_id) if ch.isalnum() or ch in "-_")
    if not safe_job or shutil.which("docker") is None:
        return 0
    filters = ["--filter", f"label=nova.job_id={safe_job}"]
    if user_id is not None:
        safe_user = "".join(ch for ch in str(user_id) if ch.isalnum() or ch in "-_")
        if safe_user:
            filters += ["--filter", f"label=nova.user_id={safe_user}"]

    def _run() -> int:
        listed = subprocess.run(
            ["docker", "ps", "-q", *filters],
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


def _run_docker_streaming(
    cmd: list[str],
    stdin_bytes: bytes | None,
    timeout: int,
    on_output: Callable[[str, str], None],
) -> tuple["subprocess.CompletedProcess", bool]:
    """Run docker with live stdout/stderr callbacks (worker-thread safe)."""
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE if stdin_bytes is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
    )
    if stdin_bytes is not None and proc.stdin:
        try:
            proc.stdin.write(stdin_bytes)
            proc.stdin.close()
        except OSError:
            pass

    chunks: "queue.Queue[tuple[str, str]]" = queue.Queue()

    def _reader(pipe, name: str) -> None:
        try:
            for line in iter(pipe.readline, b""):
                chunks.put((name, line.decode("utf-8", "replace")))
        finally:
            try:
                pipe.close()
            except OSError:
                pass

    readers = [
        threading.Thread(target=_reader, args=(proc.stdout, "stdout"), daemon=True),
        threading.Thread(target=_reader, args=(proc.stderr, "stderr"), daemon=True),
    ]
    for reader in readers:
        reader.start()

    out: list[str] = []
    err: list[str] = []
    timed_out = False
    deadline = time.monotonic() + timeout

    def _emit(name: str, text: str) -> None:
        try:
            on_output(name, text)
        except Exception:  # noqa: BLE001 - streaming must not break execution
            pass

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            timed_out = True
            try:
                proc.kill()
            except OSError:
                pass
            break
        try:
            name, text = chunks.get(timeout=min(0.2, remaining))
        except queue.Empty:
            if proc.poll() is not None and not any(t.is_alive() for t in readers):
                break
            continue
        (out if name == "stdout" else err).append(text)
        _emit(name, text)

    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
        except OSError:
            pass
        proc.wait()

    while True:
        try:
            name, text = chunks.get_nowait()
        except queue.Empty:
            break
        (out if name == "stdout" else err).append(text)
        _emit(name, text)

    return (
        subprocess.CompletedProcess(
            cmd,
            -1 if timed_out else proc.returncode,
            "".join(out).encode("utf-8"),
            "".join(err).encode("utf-8"),
        ),
        timed_out,
    )


def _shell_quote(s: str) -> str:
    return "'" + s.replace("'", "'\"'\"'") + "'"
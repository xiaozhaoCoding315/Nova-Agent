"""Host process execution for local mode.

No container, no uid change, no cgroup: commands run as the signed-in user.
The calling tool is responsible for policy/approval and for the explicit UX
warning. This module provides path containment, environment scrubbing, output
streaming, timeouts and process-tree cancellation.

Windows runs the backend under ``SelectorEventLoop`` (psycopg needs it), which
cannot create asyncio subprocesses. Commands are therefore started with
``subprocess.Popen`` and their blocking pipes are drained by daemon threads.
On Windows the command is passed to ``cmd.exe /d /s /c`` as a raw command
line: the list form lets subprocess escape the command's own quotes as
``\\"``, which cmd.exe does not understand.
"""
import asyncio
import os
import queue
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

OUTPUT_LIMIT = 100_000
_POLL_SECONDS = 0.2
_EXIT_DRAIN_SECONDS = 2.0
_KILL_WAIT_SECONDS = 5.0
_DRIVE = re.compile(r"^[A-Za-z]:")

_WIN_ALLOW = {
    "PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC",
    "TEMP", "TMP", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "APPDATA",
    "LOCALAPPDATA", "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)",
    "NUMBER_OF_PROCESSORS", "OS", "PROCESSOR_ARCHITECTURE",
}
_POSIX_ALLOW = {
    "PATH", "HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "LC_CTYPE",
    "TERM", "TMPDIR", "SHELL",
}
_SECRET_MARKERS = ("API_KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")

_RUNNING: dict[str, set[tuple[int, str]]] = {}
_WINDOWS_KERNEL32 = None


def scrub_env(extra=None, *, env=None, platform=None) -> dict[str, str]:
    """Allowlist PATH/OS variables and drop anything that looks like a secret."""
    plat = platform or sys.platform
    source = dict(os.environ if env is None else env)
    allow = _WIN_ALLOW if plat == "win32" else _POSIX_ALLOW
    out = {
        key: value for key, value in source.items()
        if key in allow or key.upper() in allow
    }
    for key, value in (extra or {}).items():
        upper = key.upper()
        if any(marker in upper for marker in _SECRET_MARKERS):
            continue
        out[key] = str(value)
    out["PYTHONIOENCODING"] = "utf-8"
    out["PYTHONUTF8"] = "1"
    return out


def resolve_cwd(root: str | Path, cwd: str = ".") -> Path:
    """Resolve ``cwd`` under ``root``, rejecting absolute paths and escapes.

    Symlinks and junctions are resolved before the containment check, so a
    link inside the project cannot be used to step outside it.
    """
    root_path = Path(root).resolve(strict=True)
    raw = str(cwd or ".").strip()
    if "\x00" in raw:
        raise ValueError("cwd 包含非法字符")
    if raw.startswith(("/", "\\")) or _DRIVE.match(raw):
        raise ValueError("cwd 必须是相对项目根目录的路径")
    candidate = (root_path / raw).resolve(strict=False)
    if candidate != root_path and root_path not in candidate.parents:
        raise ValueError("cwd 越出项目目录，必须是相对项目根目录的路径")
    if not candidate.is_dir():
        raise ValueError(f"cwd 不存在：{raw}")
    return candidate


def build_shell_argv(command: str, *, platform: str | None = None) -> list[str]:
    """Build the platform shell invocation. ``/d`` disables cmd AutoRun."""
    if not command.strip():
        raise ValueError("command 不能为空")
    if "\x00" in command:
        raise ValueError("command 包含非法字符")
    if (platform or sys.platform) == "win32":
        comspec = os.environ.get("COMSPEC", r"C:\Windows\System32\cmd.exe")
        return [comspec, "/d", "/s", "/c", command]
    return ["/bin/sh", "-c", command]


def project_python(root: str | Path) -> Path | None:
    base = Path(root)
    candidates = [
        base / ".venv" / "Scripts" / "python.exe",
        base / ".venv" / "bin" / "python",
        base / "venv" / "Scripts" / "python.exe",
        base / "venv" / "bin" / "python",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _apply_project_venv(env: dict[str, str], root: Path) -> dict[str, str]:
    python = project_python(root)
    if python is not None:
        env["VIRTUAL_ENV"] = str(python.parent.parent)
        env["PATH"] = str(python.parent) + os.pathsep + env.get("PATH", "")
    return env


def _windows_kernel32():
    global _WINDOWS_KERNEL32
    if _WINDOWS_KERNEL32 is None:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        ]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetExitCodeProcess.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        _WINDOWS_KERNEL32 = kernel32
    return _WINDOWS_KERNEL32


def pid_alive(pid: int) -> bool:
    """Whether ``pid`` is a live process (stdlib-only; avoids app.local)."""
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = _windows_kernel32()
        handle = kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, wintypes.BOOL(False), pid
        )
        if not handle:
            return False
        try:
            code = wintypes.DWORD()
            ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
            return bool(ok) and code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _kill_tree_sync(pid: int) -> None:
    if pid <= 0:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                timeout=20,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
        if pid_alive(pid):
            # taskkill missing/broken: terminate at least the shell itself.
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        return
    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


async def kill_process_tree(pid: int) -> None:
    await asyncio.to_thread(_kill_tree_sync, pid)


def _register(job_id: str, pid: int, user_id) -> None:
    _RUNNING.setdefault(str(job_id), set()).add((pid, str(user_id)))


def _unregister(job_id: str, pid: int, user_id) -> None:
    entries = _RUNNING.get(str(job_id))
    if not entries:
        return
    entries.discard((pid, str(user_id)))
    if not entries:
        _RUNNING.pop(str(job_id), None)


async def cancel_host_processes(job_id, user_id=None) -> int:
    """Kill every registered process tree for ``job_id`` (optionally per user)."""
    killed = 0
    for pid, owner in list(_RUNNING.get(str(job_id), set())):
        if user_id is not None and owner != str(user_id):
            continue
        await kill_process_tree(pid)
        killed += 1
    return killed


def _popen_platform_kwargs() -> dict:
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _popen_command(command: str) -> tuple[str | list[str], dict]:
    """Platform Popen args; Windows needs one raw command line for cmd.exe."""
    argv = build_shell_argv(command)
    if sys.platform == "win32":
        line = f'"{argv[0]}" /d /s /c "{command}"'
        return line, {"executable": argv[0]}
    return argv, {}


def _write_stdin(stream, data: bytes) -> None:
    try:
        stream.write(data)
        stream.flush()
    except OSError:
        pass
    finally:
        try:
            stream.close()
        except OSError:
            pass


def _append_bounded(
    parts: list[str], sizes: dict[str, int], name: str, text: str
) -> None:
    remaining = OUTPUT_LIMIT - sizes[name]
    if remaining <= 0:
        return
    piece = text[:remaining]
    parts.append(piece)
    sizes[name] += len(piece)


def _forward(on_output, name: str, text: str) -> None:
    if on_output is None:
        return
    try:
        on_output(name, text)
    except Exception:  # noqa: BLE001 - streaming must not break execution
        pass


def _collect_output(
    proc: subprocess.Popen,
    command: str,
    timeout: float,
    stdin_text: str,
    on_output,
) -> dict:
    """Drain pipes, enforce the deadline and kill the tree when it expires."""
    if stdin_text and proc.stdin is not None:
        threading.Thread(
            target=_write_stdin,
            args=(proc.stdin, stdin_text.encode("utf-8")),
            daemon=True,
        ).start()

    chunks: queue.Queue = queue.Queue(maxsize=256)
    eof = object()
    done = threading.Event()

    def _put(item) -> bool:
        while not done.is_set():
            try:
                chunks.put(item, timeout=0.2)
                return True
            except queue.Full:
                continue
        return False

    def _reader(pipe, name: str) -> None:
        try:
            for line in iter(pipe.readline, b""):
                if not _put((name, line.decode("utf-8", "replace"))):
                    break
        except (OSError, ValueError):
            pass
        finally:
            try:
                pipe.close()
            except OSError:
                pass
            _put(eof)

    readers = []
    for pipe, name in ((proc.stdout, "stdout"), (proc.stderr, "stderr")):
        if pipe is None:
            _put(eof)
            continue
        reader = threading.Thread(target=_reader, args=(pipe, name), daemon=True)
        reader.start()
        readers.append(reader)

    out_parts: list[str] = []
    err_parts: list[str] = []
    sizes = {"stdout": 0, "stderr": 0}
    deadline = time.monotonic() + max(0.0, float(timeout))
    timed_out = False
    eofs = 0
    exit_drain_deadline: float | None = None

    while True:
        now = time.monotonic()
        if proc.poll() is not None:
            if exit_drain_deadline is None:
                exit_drain_deadline = now + _EXIT_DRAIN_SECONDS
            elif now >= exit_drain_deadline:
                break
        elif now >= deadline:
            timed_out = True
            _kill_tree_sync(proc.pid)
            try:
                proc.wait(timeout=_KILL_WAIT_SECONDS)
            except subprocess.TimeoutExpired:
                pass
            if proc.poll() is None:
                # The tree survived the kill; do not spin on it forever.
                break
        if exit_drain_deadline is not None and eofs >= 2:
            break

        wait_for = _POLL_SECONDS
        if proc.poll() is None:
            wait_for = max(0.0, min(wait_for, deadline - time.monotonic()))
            if wait_for <= 0:
                continue
        try:
            item = chunks.get(timeout=wait_for)
        except queue.Empty:
            continue
        if item is eof:
            eofs += 1
            continue
        name, text = item
        target = out_parts if name == "stdout" else err_parts
        _append_bounded(target, sizes, name, text)
        _forward(on_output, name, text)

    done.set()
    for reader in readers:
        reader.join(timeout=0.2)

    while True:
        try:
            item = chunks.get_nowait()
        except queue.Empty:
            break
        if item is eof:
            continue
        name, text = item
        target = out_parts if name == "stdout" else err_parts
        _append_bounded(target, sizes, name, text)
        _forward(on_output, name, text)

    try:
        proc.wait(timeout=_KILL_WAIT_SECONDS)
    except subprocess.TimeoutExpired:
        pass

    return {
        "stdout": "".join(out_parts),
        "stderr": "".join(err_parts),
        "exit_code": proc.returncode if proc.returncode is not None else -1,
        "timed_out": timed_out,
        "sandboxed": False,
        "isolation": "none",
        "executor": "host",
        "command": command,
    }


async def execute_host(
    command: str,
    *,
    root: str | Path,
    cwd: str = ".",
    timeout: int = 120,
    stdin: str = "",
    env: dict[str, str] | None = None,
    on_output=None,
    job_id: str | None = None,
    user_id=None,
    venv_root: str | Path | None = None,
) -> dict:
    workdir = resolve_cwd(root, cwd)
    popen_args, popen_extra = _popen_command(command)
    child_env = _apply_project_venv(
        scrub_env(env), Path(venv_root or root).resolve()
    )

    started = time.perf_counter()
    proc = subprocess.Popen(
        popen_args,
        cwd=str(workdir),
        env=child_env,
        stdin=subprocess.PIPE if stdin else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
        **_popen_platform_kwargs(),
        **popen_extra,
    )
    if job_id:
        _register(str(job_id), proc.pid, user_id)

    try:
        result = await asyncio.to_thread(
            _collect_output, proc, command, timeout, stdin, on_output
        )
    except BaseException:
        # Cancelled task or unexpected failure: never leave a process behind.
        await kill_process_tree(proc.pid)
        raise
    finally:
        if job_id:
            _unregister(str(job_id), proc.pid, user_id)

    result["duration_ms"] = int((time.perf_counter() - started) * 1000)
    return result

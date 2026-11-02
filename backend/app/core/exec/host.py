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

Design notes and accepted limitations:

* ``taskkill /T`` is the tree-kill mechanism on Windows; the root is first
  killed through the tree so ``taskkill`` can still enumerate descendants,
  with ``Popen.kill`` as a root-only fallback. The ``Popen`` handle kept in
  the registry pins the root PID: Windows cannot recycle it while the handle
  is open, so a retained entry never refers to a different process.
* There is no Windows Job Object. A descendant that detaches and keeps
  running after the shell exits is *not* tracked by ``job_id`` once the shell
  is gone, and ``cancel_host_processes`` cannot reach it. The result is still
  returned when the shell exits (after a short drain window); reader threads
  are then cancelled and the parent pipe handles closed, so such a descendant
  cannot block the executor forever. Only processes still in the shell's tree
  can be killed with ``taskkill /T``.
* Reader threads block in ``ReadFile``. A ``done`` event alone does not
  unblock a thread already inside a pipe read: Windows uses
  ``CancelSynchronousIo`` and POSIX readers poll with ``select``.
"""
import asyncio
import locale
import logging
import os
import queue
import re
import select
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

OUTPUT_LIMIT = 100_000
MAX_LINE_BYTES = 64_000
_POLL_SECONDS = 0.2
_EXIT_DRAIN_SECONDS = 2.0
_KILL_WAIT_SECONDS = 5.0
_KILL_VERIFY_SECONDS = 1.0
_READER_JOIN_SECONDS = 0.5
_READ_CHUNK = 65_536
_DRIVE = re.compile(r"^[A-Za-z]:")
# cmd.exe expands %VAR% inside double quotes and treats these as syntax even
# when quoted in some contexts.  Values containing them are rejected rather
# than escaped: command construction must never turn repo data into syntax.
_WINDOWS_SHELL_SPECIAL = frozenset('"%!^&|<>()')

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
_SECRET_SUFFIXES = ("_KEY", "_TOKEN")
_SECRET_PARTS = ("SECRET", "PASSWORD", "CREDENTIAL")
_SECRET_PREFIXES = ("AWS_", "GOOGLE_", "AZURE_")
_SECRET_EXACT = {"GIT_SSH_COMMAND", "NODE_OPTIONS", "DATABASE_URL"}
_FORCED_ENV = {"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}

_LOG = logging.getLogger(__name__)
_REGISTRY_LOCK = threading.Lock()
_RUNNING: dict[str, dict[int, tuple[subprocess.Popen, str]]] = {}
_WINDOWS_KERNEL32 = None


def _is_secret_key(name: str) -> bool:
    """Case-insensitive denylist for caller-supplied environment entries."""
    upper = name.upper()
    if upper.endswith(_SECRET_SUFFIXES) or upper == "TOKEN":
        return True
    if any(part in upper for part in _SECRET_PARTS):
        return True
    return upper.startswith(_SECRET_PREFIXES) or upper in _SECRET_EXACT


def scrub_env(extra=None, *, env=None, platform=None) -> dict[str, str]:
    """Allowlist PATH/OS variables and drop anything that looks like a secret.

    ``extra`` entries are filtered case-insensitively: secret-looking names
    (``*_KEY``, ``*_TOKEN``, ``*SECRET*``, ``*PASSWORD*``, ``*CREDENTIAL*``,
    ``AWS_*``, ``GOOGLE_*``, ``AZURE_*``, ``GIT_SSH_COMMAND``,
    ``NODE_OPTIONS``, ``DATABASE_URL``) are ignored. They also cannot override
    the platform allowlist keys or the forced Python encoding flags; callers
    that need a different ``PATH`` should use ``venv_root`` instead.
    """
    plat = platform or sys.platform
    source = dict(os.environ if env is None else env)
    allow = _WIN_ALLOW if plat == "win32" else _POSIX_ALLOW
    protected = allow | set(_FORCED_ENV)
    out = {
        key: value for key, value in source.items()
        if key in allow or key.upper() in allow
    }
    for key, value in (extra or {}).items():
        upper = key.upper()
        if upper in protected or _is_secret_key(key):
            continue
        out[key] = str(value)
    out.update(_FORCED_ENV)
    return out


def resolve_cwd(root: str | Path, cwd: str = ".") -> Path:
    """Resolve ``cwd`` under ``root``, rejecting absolute paths and escapes.

    Symlinks and NTFS junctions are resolved before the containment check, so
    a link inside the project cannot be used to step outside it. Windows
    drive prefixes, UNC/device paths, root-relative paths and alternate data
    streams (``name:stream``) are rejected before touching the filesystem.
    """
    root_path = Path(root).resolve(strict=True)
    raw = str(cwd or ".").strip()
    if "\x00" in raw:
        raise ValueError("cwd 包含非法字符")
    if raw.startswith(("/", "\\")) or _DRIVE.match(raw):
        raise ValueError("cwd 必须是相对项目根目录的路径")
    if os.name == "nt" and ":" in raw:
        # Alternate data streams (``dir::$INDEX_ALLOCATION``) and any other
        # drive-relative form that starts with a non-letter.
        raise ValueError("cwd 必须是相对项目根目录的路径")
    candidate = (root_path / raw).resolve(strict=False)
    if candidate != root_path and root_path not in candidate.parents:
        raise ValueError("cwd 越出项目目录，必须是相对项目根目录的路径")
    if not candidate.is_dir():
        raise ValueError(f"cwd 不存在：{raw}")
    return candidate


def require_single_line(value: str, *, label: str = "参数") -> str:
    """Reject embedded newlines/NULs: cmd.exe truncates at a newline.

    Every command and every value interpolated into one goes through this or
    ``quote_shell_arg``; a silent truncation could turn a partial command into
    a different (privileged) one.
    """
    text = str(value or "")
    if "\n" in text or "\r" in text:
        raise ValueError(f"{label} 不能包含换行：命令行会被截断或拆分为多条")
    if "\x00" in text:
        raise ValueError(f"{label} 包含非法空字符")
    return text


def quote_shell_arg(value: str, *, platform: str | None = None) -> str:
    """Quote one value for the platform shell; reject cmd.exe syntax.

    POSIX uses ``shlex.quote`` (server sandboxes and POSIX hosts).  Windows
    ``cmd.exe`` has no escaping that is safe for all of ``" % ! ^ & | < > ( )``
    inside the raw line form used by this executor, so such values raise
    ``ValueError`` instead of being assembled into a command.  Legitimate
    paths containing spaces are wrapped in double quotes and keep working.
    Newlines are rejected on every platform.
    """
    text = require_single_line(value, label="参数")
    if (platform or sys.platform) == "win32":
        if any(char in _WINDOWS_SHELL_SPECIAL for char in text):
            raise ValueError(
                "参数包含 Windows Shell 特殊字符，已拒绝执行"
                "（不允许 \" % ! ^ & | < > ( ) 与换行）"
            )
        return f'"{text}"'
    return shlex.quote(text)


def build_shell_argv(command: str, *, platform: str | None = None) -> list[str]:
    """Build the platform shell invocation. ``/d`` disables cmd AutoRun."""
    if not command.strip():
        raise ValueError("command 不能为空")
    command = require_single_line(command, label="command")
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
        kernel32.OpenThread.argtypes = [
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        ]
        kernel32.OpenThread.restype = wintypes.HANDLE
        kernel32.CancelSynchronousIo.argtypes = [wintypes.HANDLE]
        kernel32.CancelSynchronousIo.restype = wintypes.BOOL
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


def _system_root() -> str:
    return os.environ.get("SystemRoot") or r"C:\Windows"


def _taskkill_path() -> str:
    """Pinned system binary; PATH search only as a last-resort fallback."""
    pinned = Path(_system_root()) / "System32" / "taskkill.exe"
    if pinned.is_file():
        return str(pinned)
    found = shutil.which("taskkill.exe")
    return found or str(pinned)


def _taskkill_env() -> dict[str, str]:
    """Minimal environment for the internal taskkill helper (no secrets)."""
    root = _system_root()
    system32 = str(Path(root) / "System32")
    return {
        "SystemRoot": root,
        "windir": root,
        "PATH": system32,
        "ComSpec": str(Path(system32) / "cmd.exe"),
    }


def _wait_for_death(pid: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while True:
        if not pid_alive(pid):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.02)


def _kill_tree_sync(pid: int) -> bool:
    """Kill ``pid`` and its tree; return True when the root is confirmed dead."""
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            subprocess.run(
                [_taskkill_path(), "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                timeout=20,
                env=_taskkill_env(),
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
        if pid_alive(pid):
            # taskkill missing/broken: terminate at least the shell itself.
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        return _wait_for_death(pid, _KILL_VERIFY_SECONDS)
    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    return _wait_for_death(pid, _KILL_VERIFY_SECONDS)


async def kill_process_tree(pid: int) -> None:
    await asyncio.to_thread(_kill_tree_sync, pid)


def _register(job_id: str, proc: subprocess.Popen, user_id) -> None:
    with _REGISTRY_LOCK:
        _RUNNING.setdefault(str(job_id), {})[proc.pid] = (proc, str(user_id))


def _unregister(job_id: str, pid: int, user_id) -> None:
    with _REGISTRY_LOCK:
        entries = _RUNNING.get(str(job_id))
        if not entries:
            return
        entries.pop(pid, None)
        if not entries:
            _RUNNING.pop(str(job_id), None)


async def cancel_host_processes(job_id, user_id=None) -> int:
    """Kill registered trees for ``job_id``; count only confirmed kills.

    Entries whose kill cannot be confirmed stay registered (and keep their
    ``Popen`` handle) so a later cancel can retry without risking PID reuse.
    """
    with _REGISTRY_LOCK:
        entries = list((_RUNNING.get(str(job_id)) or {}).items())
    killed = 0
    for pid, (proc, owner) in entries:
        if user_id is not None and owner != str(user_id):
            continue
        if proc.poll() is not None:
            # Already dead: remove the entry instead of risking PID reuse.
            _unregister(str(job_id), pid, owner)
            continue
        confirmed = await asyncio.to_thread(_kill_tree_sync, pid)
        if not confirmed and proc.poll() is not None:
            confirmed = True
        if confirmed:
            killed += 1
            _unregister(str(job_id), pid, owner)
        else:
            _LOG.warning("host_kill_failed job_id=%s pid=%s", job_id, pid)
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
) -> bool:
    """Append up to the per-stream cap; return True when text was dropped."""
    remaining = OUTPUT_LIMIT - sizes[name]
    if remaining <= 0:
        return bool(text)
    piece = text[:remaining]
    if piece:
        parts.append(piece)
        sizes[name] += len(piece)
    return len(text) > len(piece)


def _forward(on_output, name: str, text: str, state: dict) -> None:
    if on_output is None:
        return
    try:
        on_output(name, text)
    except Exception as exc:  # noqa: BLE001 - streaming must not break execution
        if not state.get("warned"):
            state["warned"] = True
            _LOG.warning(
                "host_on_output_failed stream=%s error=%s",
                name,
                type(exc).__name__,
            )


def _preferred_output_encoding() -> str:
    if os.name != "nt":
        return "utf-8"
    try:
        return locale.getpreferredencoding(False) or "mbcs"
    except (LookupError, ValueError):
        return "mbcs"


def _decode_output(data: bytes, encoding: str) -> str:
    """Decode a line: UTF-8 first (Python children), then the console codepage.

    ``execute_host`` forces Python children to UTF-8 via ``PYTHONIOENCODING``,
    while ``cmd.exe``/native tools emit bytes in the active code page. Strict
    UTF-8 succeeds for the former; otherwise the fallback keeps Chinese
    ``cmd.exe`` output readable instead of producing replacement characters.
    Every failure path uses ``errors="replace"`` and never raises.
    """
    if encoding == "utf-8":
        return data.decode("utf-8", "replace")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode(encoding, "replace")


def _put_item(chunks: queue.Queue, stop: threading.Event, item) -> bool:
    while not stop.is_set():
        try:
            chunks.put(item, timeout=0.2)
            return True
        except queue.Full:
            continue
    return False


def _read_chunk(pipe, stop: threading.Event) -> bytes:
    if os.name == "nt":
        return pipe.read(_READ_CHUNK)
    fd = pipe.fileno()
    while not stop.is_set():
        ready, _, _ = select.select([fd], [], [], _POLL_SECONDS)
        if ready:
            return os.read(fd, _READ_CHUNK)
    return b""


def _stream_reader(
    pipe,
    name: str,
    stop: threading.Event,
    chunks: queue.Queue,
    encoding: str,
    eof,
) -> None:
    """Split a pipe into bounded lines and queue them for the collector."""
    pending = bytearray()
    dropping = False

    def emit(truncated: bool) -> bool:
        nonlocal pending
        if not pending:
            return True
        text = _decode_output(bytes(pending), encoding)
        pending = bytearray()
        return _put_item(chunks, stop, (name, text, truncated))

    try:
        while not stop.is_set():
            chunk = _read_chunk(pipe, stop)
            if not chunk:
                break
            index = 0
            while index < len(chunk):
                newline = chunk.find(b"\n", index)
                if newline < 0:
                    if not dropping:
                        room = MAX_LINE_BYTES - len(pending)
                        if room > 0:
                            pending.extend(chunk[index:index + room])
                        if len(chunk) - index > room:
                            dropping = True
                    break
                segment = chunk[index:newline + 1]
                index = newline + 1
                if dropping:
                    if not emit(True):
                        return
                    dropping = False
                    continue
                room = MAX_LINE_BYTES - len(pending)
                if len(segment) > room:
                    if room > 0:
                        pending.extend(segment[:room])
                    if not emit(True):
                        return
                else:
                    pending.extend(segment)
                    if not emit(False):
                        return
        if pending:
            emit(dropping)
    except (OSError, ValueError):
        pass
    finally:
        try:
            pipe.close()
        except (OSError, ValueError):
            pass
        _put_item(chunks, stop, eof)


def _cancel_reader_io(reader: threading.Thread) -> None:
    """Abort a Windows ``ReadFile`` blocked in ``reader`` (no-op elsewhere)."""
    if os.name != "nt" or not reader.is_alive():
        return
    native_id = reader.native_id
    if native_id is None:
        return
    try:
        kernel32 = _windows_kernel32()
        handle = kernel32.OpenThread(0x0001, False, native_id)
        if not handle:
            return
        try:
            kernel32.CancelSynchronousIo(handle)
        finally:
            kernel32.CloseHandle(handle)
    except (AttributeError, OSError):
        pass


def _stop_readers(readers: list[tuple[threading.Thread, object]]) -> None:
    # Two attempts: CancelSynchronousIo can miss a reader that has passed the
    # stop check but has not yet entered ReadFile.
    for _ in range(2):
        for reader, _ in readers:
            _cancel_reader_io(reader)
        for reader, _ in readers:
            if reader.is_alive():
                reader.join(timeout=_READER_JOIN_SECONDS)


def _close_pipe(stream) -> None:
    if stream is None:
        return
    try:
        stream.close()
    except (OSError, ValueError):
        pass


def _collect_output(
    proc: subprocess.Popen,
    command: str,
    timeout: float,
    stdin_text: str,
    on_output,
    job_id: str | None = None,
) -> dict:
    """Drain pipes, enforce the deadline and kill the tree when it expires."""
    if stdin_text and proc.stdin is not None:
        threading.Thread(
            target=_write_stdin,
            args=(proc.stdin, stdin_text.encode("utf-8")),
            daemon=True,
            name="host-stdin",
        ).start()

    chunks: queue.Queue = queue.Queue(maxsize=256)
    eof = object()
    stop = threading.Event()
    encoding = _preferred_output_encoding()

    readers: list[tuple[threading.Thread, object]] = []
    expected_eofs = 0
    for pipe, name in ((proc.stdout, "stdout"), (proc.stderr, "stderr")):
        if pipe is None:
            chunks.put_nowait(eof)
            expected_eofs += 1
            continue
        reader = threading.Thread(
            target=_stream_reader,
            args=(pipe, name, stop, chunks, encoding, eof),
            daemon=True,
            name=f"host-reader-{name}",
        )
        reader.start()
        readers.append((reader, pipe))
        expected_eofs += 1

    out_parts: list[str] = []
    err_parts: list[str] = []
    sizes = {"stdout": 0, "stderr": 0}
    forwarded: dict = {"warned": False}
    deadline = time.monotonic() + max(0.0, float(timeout))
    timed_out = False
    kill_failed = False
    output_truncated = False
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
            killed = _kill_tree_sync(proc.pid)
            if not killed or proc.poll() is None:
                try:
                    proc.kill()
                except OSError:
                    pass
            try:
                proc.wait(timeout=_KILL_WAIT_SECONDS)
            except subprocess.TimeoutExpired:
                pass
            if proc.poll() is None:
                # Do not report success for a process that survived the kill.
                kill_failed = True
                _LOG.warning(
                    "host_kill_failed job_id=%s pid=%s timed_out=true",
                    job_id,
                    proc.pid,
                )
                break
        if exit_drain_deadline is not None and eofs >= expected_eofs:
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
        name, text, truncated = item
        target = out_parts if name == "stdout" else err_parts
        if _append_bounded(target, sizes, name, text):
            output_truncated = True
        if truncated:
            output_truncated = True
        _forward(on_output, name, text, forwarded)

    stop.set()
    _stop_readers(readers)
    for reader, pipe in readers:
        if reader.is_alive():
            # Last resort: leave the daemon reader owning its pipe rather than
            # blocking this collector in a cross-thread close.
            _LOG.warning("host_reader_stuck name=%s", reader.name)
        else:
            _close_pipe(pipe)

    while True:
        try:
            item = chunks.get_nowait()
        except queue.Empty:
            break
        if item is eof:
            continue
        name, text, truncated = item
        target = out_parts if name == "stdout" else err_parts
        if _append_bounded(target, sizes, name, text):
            output_truncated = True
        if truncated:
            output_truncated = True
        _forward(on_output, name, text, forwarded)

    if not kill_failed:
        try:
            proc.wait(timeout=_KILL_WAIT_SECONDS)
        except subprocess.TimeoutExpired:
            pass

    return {
        "stdout": "".join(out_parts),
        "stderr": "".join(err_parts),
        "exit_code": proc.returncode if proc.returncode is not None else -1,
        "timed_out": timed_out,
        "kill_failed": kill_failed,
        "output_truncated": output_truncated,
        "sandboxed": False,
        "isolation": "none",
        "executor": "host",
        "command": command,
    }


async def _execute_process(
    popen_args,
    popen_extra: dict,
    display_command: str,
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
    """Shared spawn/collect path for shell and direct-argv execution."""
    workdir = resolve_cwd(root, cwd)
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
        _register(str(job_id), proc, user_id)

    try:
        result = await asyncio.to_thread(
            _collect_output, proc, display_command, timeout, stdin, on_output, job_id
        )
    except BaseException:
        # Cancelled task or unexpected failure: never leave a process behind.
        await asyncio.to_thread(_kill_tree_sync, proc.pid)
        if proc.poll() is None:
            try:
                proc.kill()
            except OSError:
                pass
            try:
                proc.wait(timeout=_KILL_WAIT_SECONDS)
            except subprocess.TimeoutExpired:
                pass
        if proc.poll() is None:
            _LOG.warning("host_kill_failed job_id=%s pid=%s", job_id, proc.pid)
        elif job_id:
            _unregister(str(job_id), proc.pid, user_id)
        raise
    else:
        # A process that survived its kill keeps its registry entry (and its
        # Popen handle) so a later cancel can reach it.
        if job_id and not result["kill_failed"]:
            _unregister(str(job_id), proc.pid, user_id)

    result["duration_ms"] = int((time.perf_counter() - started) * 1000)
    return result


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
    popen_args, popen_extra = _popen_command(command)
    return await _execute_process(
        popen_args,
        popen_extra,
        command,
        root=root,
        cwd=cwd,
        timeout=timeout,
        stdin=stdin,
        env=env,
        on_output=on_output,
        job_id=job_id,
        user_id=user_id,
        venv_root=venv_root,
    )


def _validate_argv(argv) -> list[str]:
    """Fixed-argv callers must pass non-empty, newline-free strings."""
    if not isinstance(argv, (list, tuple)) or not argv:
        raise ValueError("argv 不能为空")
    out: list[str] = []
    for item in argv:
        if not isinstance(item, str):
            raise ValueError("argv 的每一项都必须是字符串")
        if not item or "\x00" in item or "\n" in item or "\r" in item:
            raise ValueError("argv 含空项或非法字符")
        out.append(item)
    return out


def argv_display(argv: list[str]) -> str:
    """Display-only command string; never fed back to a shell here."""
    if os.name == "nt":
        return subprocess.list2cmdline(argv)
    return shlex.join(argv)


async def execute_argv_host(
    argv: list[str],
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
    """Run ``argv`` directly (``shell=False``) on the host.

    Fixed-argv callers (diagnostics runners) must not pass repo data through a
    shell.  Path containment, env scrubbing, timeouts and tree cancellation
    are shared with :func:`execute_host`.
    """
    args = _validate_argv(argv)
    return await _execute_process(
        args,
        {},
        argv_display(args),
        root=root,
        cwd=cwd,
        timeout=timeout,
        stdin=stdin,
        env=env,
        on_output=on_output,
        job_id=job_id,
        user_id=user_id,
        venv_root=venv_root,
    )

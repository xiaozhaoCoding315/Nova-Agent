"""Windows Job Object that kills the local runtime's descendants on exit.

``pgserver`` starts PostgreSQL through an intermediate ``cmd.exe /C``, so the
postmaster is *not* a descendant of the backend process: ``taskkill /T`` on
the backend misses it, and a forced kill (Task Manager, a CI runner ending
the job, a crash) never runs the launcher's ``finally: pg.stop()``. The
postmaster then survives as an orphan holding the data directory and its port.

Joining a job object configured with ``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE``
makes Windows terminate every process in the job when the last handle to it
closes. Windows closes the handle when the process dies, however it dies, so
the postmaster is reaped even when no Python cleanup code runs.

The handle must outlive the process. A handle that is garbage collected would
close the job and kill the very processes this module protects, so the job is
kept alive in a module-level registry for the process lifetime.
"""
import sys
import threading

# Job object limit flag: terminate all processes when the last handle closes.
_KILL_ON_JOB_CLOSE = 0x00002000
_EXTENDED_LIMIT_INFORMATION = 9

_JOBS: dict[str, "_JobObject"] = {}
_LOCK = threading.Lock()


class _JobObject:
    """Thin owner of one Win32 job handle."""

    def __init__(self, handle: int, kernel32) -> None:
        self.handle = handle
        self._kernel32 = kernel32
        self._closed = False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._kernel32.CloseHandle(self.handle)
        except Exception:  # noqa: BLE001 - shutdown must never raise
            pass


def _build_job(kernel32):
    """Create a kill-on-close job and join this process to it."""
    import ctypes
    import ctypes.wintypes as wt

    class _BasicLimits(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wt.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wt.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wt.DWORD),
            ("SchedulingClass", wt.DWORD),
        ]

    class _IoCounters(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_uint64),
            ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64),
            ("ReadTransferCount", ctypes.c_uint64),
            ("WriteTransferCount", ctypes.c_uint64),
            ("OtherTransferCount", ctypes.c_uint64),
        ]

    class _ExtendedLimits(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _BasicLimits),
            ("IoInfo", _IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel32.CreateJobObjectW.restype = wt.HANDLE
    kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wt.LPCWSTR]
    kernel32.SetInformationJobObject.argtypes = [
        wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD
    ]
    kernel32.SetInformationJobObject.restype = wt.BOOL
    kernel32.AssignProcessToJobObject.argtypes = [wt.HANDLE, wt.HANDLE]
    kernel32.AssignProcessToJobObject.restype = wt.BOOL
    kernel32.CloseHandle.argtypes = [wt.HANDLE]
    kernel32.CloseHandle.restype = wt.BOOL

    handle = kernel32.CreateJobObjectW(None, None)
    if not handle:
        return None
    limits = _ExtendedLimits()
    limits.BasicLimitInformation.LimitFlags = _KILL_ON_JOB_CLOSE
    configured = kernel32.SetInformationJobObject(
        handle,
        _EXTENDED_LIMIT_INFORMATION,
        ctypes.byref(limits),
        ctypes.sizeof(limits),
    )
    if not configured:
        kernel32.CloseHandle(handle)
        return None
    # A process can belong to more than one job (nested jobs since Windows 8).
    assigned = kernel32.AssignProcessToJobObject(handle, kernel32.GetCurrentProcess())
    if not assigned:
        kernel32.CloseHandle(handle)
        return None
    return _JobObject(handle, kernel32)


def join_kill_on_close_job(name: str = "nova-local"):
    """Join this process to a kill-on-close job; return the job or ``None``.

    Returns ``None`` off Windows or when the platform refuses the job (for
    example an older Windows that cannot nest jobs), because losing this
    safety net must not prevent the runtime from starting. Callers may
    therefore not assume the job exists.
    """
    if sys.platform != "win32":
        return None
    with _LOCK:
        existing = _JOBS.get(name)
        if existing is not None:
            return existing
        try:
            import ctypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        except Exception:  # noqa: BLE001 - optional hardening
            return None
        try:
            job = _build_job(kernel32)
        except Exception:  # noqa: BLE001 - optional hardening
            return None
        if job is not None:
            _JOBS[name] = job
        return job


def current_job(name: str = "nova-local"):
    """Return the job already joined under ``name`` without creating one."""
    with _LOCK:
        return _JOBS.get(name)


def close_job(name: str = "nova-local") -> None:
    """Close the job handle; this terminates every process still in the job.

    Only tests should call this: the runtime deliberately keeps the handle
    open so Windows can reap descendants when the process dies.
    """
    with _LOCK:
        job = _JOBS.pop(name, None)
    if job is not None:
        job.close()


def is_supported() -> bool:
    """Whether a job could be joined on this platform."""
    return sys.platform == "win32"

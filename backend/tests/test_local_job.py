import os
import subprocess
import sys
import textwrap
import time

import pytest

from app.local import job as local_job

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="Windows job objects"
)


def _pid_alive(pid: int) -> bool:
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command", f"(Get-Process -Id {pid} -ErrorAction SilentlyContinue).Id"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    return bool(out)


def test_join_returns_job_and_is_idempotent():
    first = local_job.join_kill_on_close_job()
    assert first is not None
    assert local_job.join_kill_on_close_job() is first
    assert local_job.current_job() is first


def test_is_supported_matches_platform():
    assert local_job.is_supported() is True


def test_close_job_on_unknown_name_is_a_noop():
    # Never close a job the current process joined: closing the handle
    # terminates every process in it, including the caller.
    assert local_job.current_job("never-joined") is None
    local_job.close_job("never-joined")


# A grandchild started through an intermediate cmd.exe is not in the parent's
# process tree, which is exactly how pgserver starts PostgreSQL.
_SCRIPT = textwrap.dedent(
    """
    import subprocess, sys, time
    sys.path.insert(0, r"{backend}")
    from app.local import job as local_job
    assert local_job.join_kill_on_close_job("spawner") is not None
    proc = subprocess.Popen(
        ["cmd.exe", "/D", "/C", "ping -n 200 127.0.0.1 > nul"],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    print(proc.pid, flush=True)
    time.sleep(100000)
    """
)


def test_forced_kill_reaps_descendants(tmp_path):
    backend = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script = tmp_path / "spawner.py"
    script.write_text(_SCRIPT.format(backend=backend), encoding="utf-8")

    proc = subprocess.Popen(
        [sys.executable, str(script)],
        stdout=subprocess.PIPE,
        text=True,
    )
    assert proc.stdout is not None
    grandchild = int(proc.stdout.readline().strip())
    assert _pid_alive(grandchild)

    # TerminateProcess: no Python cleanup runs, mirroring a crash or a
    # Task Manager kill of the backend.
    proc.kill()
    proc.wait(timeout=10)

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and _pid_alive(grandchild):
        time.sleep(0.2)
    assert not _pid_alive(grandchild), "job object did not reap the grandchild"

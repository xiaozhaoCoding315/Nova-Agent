import asyncio
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from app.core.exec import host


async def _wait_registered(job_id, timeout=5.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        entries = host._RUNNING.get(job_id) or {}
        if entries:
            return next(iter(entries))
        await asyncio.sleep(0.05)
    raise AssertionError(f"{job_id} was not registered")


async def _wait_dead(pid, timeout=5.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if not host.pid_alive(pid):
            return True
        await asyncio.sleep(0.05)
    return not host.pid_alive(pid)


async def _wait_file(path, timeout=5.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if path.is_file():
            return path
        await asyncio.sleep(0.05)
    raise AssertionError(f"{path} was not written")


def test_scrub_env_keeps_allowlisted_and_drops_secrets():
    env = {
        "PATH": "C:/Windows/System32",
        "SYSTEMROOT": "C:/Windows",
        "TEMP": "C:/Temp",
        "HOME": "C:/Users/alice",
        "AWS_PROFILE": "prod",
        "ZHIPU_API_KEY": "sk-secret",
        "NOVA_TOKEN": "token",
        "SECRET_KEY": "leak",
    }
    cleaned = host.scrub_env(env=env, platform="win32")
    assert cleaned["PATH"] == "C:/Windows/System32"
    assert cleaned["SYSTEMROOT"] == "C:/Windows"
    assert "AWS_PROFILE" not in cleaned
    assert "ZHIPU_API_KEY" not in cleaned
    assert "NOVA_TOKEN" not in cleaned
    assert "SECRET_KEY" not in cleaned


def test_scrub_env_filters_explicit_values():
    cleaned = host.scrub_env(
        {"PYTHONPATH": "C:/work", "MY_API_KEY": "secret", "NO_PROXY": "localhost"},
        env={"PATH": "C:/bin"},
        platform="win32",
    )
    assert cleaned["PYTHONPATH"] == "C:/work"
    assert cleaned["NO_PROXY"] == "localhost"
    assert "MY_API_KEY" not in cleaned


def test_scrub_env_denies_extended_secrets_and_protects_core_keys():
    extra = {
        "lower_key": "x",
        "SERVICE_TOKEN": "x",
        "APP_SECRET_VALUE": "x",
        "DB_PASSWORD": "x",
        "USER_CREDENTIALS": "x",
        "AWS_PROFILE": "x",
        "GOOGLE_APPLICATION_CREDENTIALS": "x",
        "AZURE_CLIENT_ID": "x",
        "GIT_SSH_COMMAND": "x",
        "NODE_OPTIONS": "x",
        "DATABASE_URL": "x",
        "PATH": "evil",
        "path": "evil",
        "SystemRoot": "evil",
        "comspec": "evil",
        "PYTHONIOENCODING": "latin-1",
        "PYTHONUTF8": "0",
        "PYTHONDONTWRITEBYTECODE": "0",
        "PYTHONPATH": "C:/work",
        "NO_PROXY": "localhost",
    }
    cleaned = host.scrub_env(
        extra,
        env={"PATH": "C:/bin", "SYSTEMROOT": "C:/Windows"},
        platform="win32",
    )
    for denied in (
        "lower_key",
        "SERVICE_TOKEN",
        "APP_SECRET_VALUE",
        "DB_PASSWORD",
        "USER_CREDENTIALS",
        "AWS_PROFILE",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "AZURE_CLIENT_ID",
        "GIT_SSH_COMMAND",
        "NODE_OPTIONS",
        "DATABASE_URL",
        "SystemRoot",
        "comspec",
    ):
        assert denied not in cleaned
    assert cleaned["PATH"] == "C:/bin"
    assert cleaned["SYSTEMROOT"] == "C:/Windows"
    assert cleaned["PYTHONIOENCODING"] == "utf-8"
    assert cleaned["PYTHONUTF8"] == "1"
    # Host runs must not leave __pycache__ in the real repository.
    assert cleaned["PYTHONDONTWRITEBYTECODE"] == "1"
    assert cleaned["PYTHONPATH"] == "C:/work"
    assert cleaned["NO_PROXY"] == "localhost"


def test_resolve_cwd_accepts_subdirectory_with_spaces(tmp_path):
    child = tmp_path / "sub dir"
    child.mkdir()
    assert host.resolve_cwd(tmp_path, "sub dir") == child.resolve()


def test_resolve_cwd_rejects_traversal_and_absolute(tmp_path):
    with pytest.raises(ValueError, match="相对"):
        host.resolve_cwd(tmp_path, "..")
    with pytest.raises(ValueError, match="相对"):
        host.resolve_cwd(tmp_path, str(tmp_path))
    with pytest.raises(ValueError, match="相对"):
        host.resolve_cwd(tmp_path, "C:/Windows")


def test_resolve_cwd_rejects_unc_device_and_root_relative(tmp_path):
    for bad in (r"\\server\share", r"\\?\C:\Windows", r"\Windows", "C:Windows"):
        with pytest.raises(ValueError, match="相对"):
            host.resolve_cwd(tmp_path, bad)


@pytest.mark.skipif(os.name != "nt", reason="NTFS alternate data streams")
def test_resolve_cwd_rejects_alternate_data_stream(tmp_path):
    (tmp_path / "dir").mkdir()
    with pytest.raises(ValueError, match="相对"):
        host.resolve_cwd(tmp_path, "dir::$INDEX_ALLOCATION")


def test_resolve_cwd_missing_or_file_root(tmp_path):
    with pytest.raises(FileNotFoundError):
        host.resolve_cwd(tmp_path / "missing", ".")
    file_root = tmp_path / "root.txt"
    file_root.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="cwd"):
        host.resolve_cwd(file_root, ".")


@pytest.mark.skipif(os.name != "nt", reason="NTFS junction creation")
def test_resolve_cwd_rejects_junction_escape(tmp_path):
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    link = tmp_path / "escape"
    try:
        created = subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(outside)],
            capture_output=True,
            timeout=30,
        )
        if created.returncode != 0:
            pytest.skip("junction creation failed")
        with pytest.raises(ValueError, match="相对"):
            host.resolve_cwd(tmp_path, "escape")
    finally:
        if link.is_symlink() or link.exists():
            try:
                os.rmdir(link)
            except OSError:
                pass
        shutil.rmtree(outside, ignore_errors=True)


def test_resolve_cwd_rejects_symlink_escape(tmp_path):
    outside = tmp_path.parent / f"{tmp_path.name}-symlink-outside"
    outside.mkdir()
    link = tmp_path / "escape"
    try:
        try:
            os.symlink(outside, link, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("symlink creation not permitted")
        with pytest.raises(ValueError, match="相对"):
            host.resolve_cwd(tmp_path, "escape")
    finally:
        if link.is_symlink():
            try:
                link.unlink()
            except OSError:
                pass
        shutil.rmtree(outside, ignore_errors=True)


def test_build_shell_argv_uses_cmd_without_autorun(monkeypatch):
    monkeypatch.setenv("COMSPEC", r"C:\Windows\System32\cmd.exe")
    argv = host.build_shell_argv("echo hi", platform="win32")
    assert argv[1:] == ["/d", "/s", "/c", "echo hi"]
    assert argv[0].lower().endswith("cmd.exe")


def test_build_shell_argv_posix():
    assert host.build_shell_argv("echo hi", platform="linux") == ["/bin/sh", "-c", "echo hi"]


def test_project_python_detects_venv(tmp_path):
    python = tmp_path / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    python.parent.mkdir(parents=True)
    python.touch()
    assert host.project_python(tmp_path) == python


@pytest.mark.skipif(os.name != "nt", reason="taskkill is Windows-only")
def test_kill_tree_uses_pinned_taskkill_and_scrubbed_env(monkeypatch):
    calls = []

    class Completed:
        returncode = 0

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return Completed()

    monkeypatch.setenv("SECRET_KEY", "must-not-leak")
    monkeypatch.setattr(host.subprocess, "run", fake_run)
    monkeypatch.setattr(host, "pid_alive", lambda pid: False)

    assert host._kill_tree_sync(4242) is True
    assert len(calls) == 1
    argv, kwargs = calls[0]
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    expected = Path(system_root) / "System32" / "taskkill.exe"
    assert Path(argv[0]) == expected
    assert argv[1:] == ["/PID", "4242", "/T", "/F"]
    env = kwargs["env"]
    assert env["SystemRoot"] == system_root
    assert Path(env["PATH"]) == expected.parent
    assert "SECRET_KEY" not in env


@pytest.mark.asyncio
async def test_execute_host_runs_command_and_marks_no_isolation(tmp_path):
    command = f'"{sys.executable}" -c "print(\'host-ok\')"'
    result = await host.execute_host(command, root=tmp_path, timeout=10)
    assert result["stdout"].strip() == "host-ok"
    assert result["exit_code"] == 0
    assert result["sandboxed"] is False
    assert result["isolation"] == "none"
    assert result["executor"] == "host"
    assert result["kill_failed"] is False
    assert result["output_truncated"] is False


@pytest.mark.asyncio
async def test_execute_host_strips_secret_env(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVA_TEST_TOKEN", "must-not-leak")
    command = (
        f'"{sys.executable}" -c '
        f'"import os; print(os.getenv(\'NOVA_TEST_TOKEN\', \'missing\'))"'
    )
    result = await host.execute_host(command, root=tmp_path, timeout=10)
    assert result["stdout"].strip() == "missing"


@pytest.mark.skipif(os.name != "nt", reason="Windows console code page")
@pytest.mark.asyncio
async def test_execute_host_decodes_chinese_cmd_output(tmp_path):
    result = await host.execute_host("echo 中文", root=tmp_path, timeout=10)
    assert result["stdout"].strip() == "中文"


@pytest.mark.asyncio
async def test_execute_host_decodes_utf8_python_output(tmp_path):
    command = f'"{sys.executable}" -c "print(\'中文\')"'
    result = await host.execute_host(command, root=tmp_path, timeout=10)
    assert result["stdout"].strip() == "中文"


@pytest.mark.asyncio
async def test_execute_host_timeout_kills_process_tree(tmp_path):
    script = tmp_path / "spawn.py"
    script.write_text(
        "import subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "open(sys.argv[1], 'w').write(str(child.pid))\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )
    marker = tmp_path / "child.pid"
    command = f'"{sys.executable}" "{script}" "{marker}"'
    task = asyncio.create_task(
        host.execute_host(
            command, root=tmp_path, timeout=4, job_id="job-timeout", user_id=7
        )
    )
    root_pid = await _wait_registered("job-timeout")
    result = await task
    assert result["timed_out"] is True
    assert result["kill_failed"] is False
    assert marker.is_file()
    child_pid = int(marker.read_text(encoding="utf-8"))
    assert await _wait_dead(child_pid)
    assert not host.pid_alive(root_pid)
    assert "job-timeout" not in host._RUNNING


@pytest.mark.asyncio
async def test_cancel_host_processes_by_job_id(tmp_path):
    command = f'"{sys.executable}" -c "import time; time.sleep(60)"'
    task = asyncio.create_task(
        host.execute_host(command, root=tmp_path, timeout=30, job_id="job-1", user_id=7)
    )
    pid = await _wait_registered("job-1")
    killed = await host.cancel_host_processes("job-1", 7)
    result = await task
    assert killed == 1
    assert result["timed_out"] is False
    assert result["kill_failed"] is False
    assert result["exit_code"] != 0
    assert not host.pid_alive(pid)


@pytest.mark.asyncio
async def test_cancel_host_processes_ignores_other_user(tmp_path):
    command = f'"{sys.executable}" -c "import time; time.sleep(10)"'
    task = asyncio.create_task(
        host.execute_host(command, root=tmp_path, timeout=30, job_id="job-2", user_id=7)
    )
    pid = await _wait_registered("job-2")
    assert await host.cancel_host_processes("job-2", 99) == 0
    assert host.pid_alive(pid)
    assert await host.cancel_host_processes("job-2", 7) == 1
    await task
    assert not host.pid_alive(pid)


@pytest.mark.asyncio
async def test_cancel_host_processes_kills_grandchild(tmp_path):
    script = tmp_path / "cancel_tree.py"
    script.write_text(
        "import subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "open(sys.argv[1], 'w').write(str(child.pid))\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )
    marker = tmp_path / "grandchild.pid"
    command = f'"{sys.executable}" "{script}" "{marker}"'
    task = asyncio.create_task(
        host.execute_host(
            command, root=tmp_path, timeout=30, job_id="job-grand", user_id=7
        )
    )
    root_pid = await _wait_registered("job-grand")
    await _wait_file(marker)
    grandchild_pid = int(marker.read_text(encoding="utf-8"))
    assert await host.cancel_host_processes("job-grand", 7) == 1
    result = await task
    assert result["timed_out"] is False
    assert not host.pid_alive(root_pid)
    assert await _wait_dead(grandchild_pid)


@pytest.mark.asyncio
async def test_kill_failure_is_surfaced_and_registry_retained(tmp_path, monkeypatch):
    command = f'"{sys.executable}" -c "import time; time.sleep(60)"'
    original_kill = host._kill_tree_sync
    monkeypatch.setattr(host, "_kill_tree_sync", lambda pid: False)
    monkeypatch.setattr(subprocess.Popen, "kill", lambda self: None)
    monkeypatch.setattr(host, "_KILL_WAIT_SECONDS", 0.3)

    result = await host.execute_host(
        command, root=tmp_path, timeout=1, job_id="job-kill-fail", user_id=7
    )

    assert result["timed_out"] is True
    assert result["kill_failed"] is True
    assert result["exit_code"] == -1
    entries = host._RUNNING.get("job-kill-fail") or {}
    assert entries
    pid = next(iter(entries))
    proc = entries[pid][0]
    assert host.pid_alive(pid)
    try:
        assert await asyncio.to_thread(original_kill, pid) is True
        proc.wait(timeout=5)
    finally:
        host._unregister("job-kill-fail", pid, "7")
    assert not host.pid_alive(pid)


@pytest.mark.asyncio
async def test_cancel_counts_only_confirmed_kills(monkeypatch, caplog):
    job = "job-unconfirmed"

    class DummyProc:
        def poll(self):
            return None

    with host._REGISTRY_LOCK:
        host._RUNNING[job] = {424242: (DummyProc(), "7")}
    monkeypatch.setattr(host, "_kill_tree_sync", lambda pid: False)
    try:
        with caplog.at_level(logging.WARNING, logger=host.__name__):
            assert await host.cancel_host_processes(job, 7) == 0
        assert job in host._RUNNING
        assert any("host_kill_failed" in r.getMessage() for r in caplog.records)
    finally:
        with host._REGISTRY_LOCK:
            host._RUNNING.pop(job, None)


@pytest.mark.asyncio
async def test_on_output_failures_warn_once_without_command_text(tmp_path, caplog):
    calls = []
    marker = "do-not-log-this-command"

    def broken(stream, text):
        calls.append((stream, text))
        raise RuntimeError("boom")

    command = (
        f'"{sys.executable}" -c '
        f'"print(\'one\'); print(\'{marker}\')"'
    )
    with caplog.at_level(logging.WARNING, logger=host.__name__):
        result = await host.execute_host(
            command, root=tmp_path, timeout=10, on_output=broken
        )
    assert result["exit_code"] == 0
    assert len(calls) >= 2
    warnings = [r for r in caplog.records if "host_on_output_failed" in r.getMessage()]
    assert len(warnings) == 1
    assert marker not in caplog.text


@pytest.mark.asyncio
async def test_output_line_cap_sets_truncated_flag(tmp_path):
    command = f'"{sys.executable}" -c "print(\'x\' * 200000)"'
    result = await host.execute_host(command, root=tmp_path, timeout=20)
    assert result["exit_code"] == 0
    assert result["output_truncated"] is True
    assert len(result["stdout"]) <= host.MAX_LINE_BYTES + 2


@pytest.mark.asyncio
async def test_output_total_cap_sets_truncated_flag(tmp_path):
    command = f'"{sys.executable}" -c "for _ in range(200): print(\'y\' * 1000)"'
    result = await host.execute_host(command, root=tmp_path, timeout=20)
    assert result["exit_code"] == 0
    assert result["output_truncated"] is True
    assert len(result["stdout"]) <= host.OUTPUT_LIMIT


@pytest.mark.asyncio
async def test_reader_threads_stop_when_descendant_holds_pipes(tmp_path):
    script = tmp_path / "detach.py"
    script.write_text(
        "import subprocess, sys\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
        "open(sys.argv[1], 'w').write(str(child.pid))\n",
        encoding="utf-8",
    )
    marker = tmp_path / "detached.pid"
    command = f'"{sys.executable}" "{script}" "{marker}"'
    child_pid = None
    try:
        started = time.monotonic()
        result = await host.execute_host(command, root=tmp_path, timeout=20)
        elapsed = time.monotonic() - started
        await _wait_file(marker)
        child_pid = int(marker.read_text(encoding="utf-8"))
        assert result["exit_code"] == 0
        assert result["timed_out"] is False
        assert elapsed < 10
        leftovers = [
            thread
            for thread in threading.enumerate()
            if thread.name.startswith("host-reader-") and thread.is_alive()
        ]
        assert leftovers == []
    finally:
        if child_pid is None and marker.is_file():
            child_pid = int(marker.read_text(encoding="utf-8"))
        if child_pid is not None:
            assert await asyncio.to_thread(host._kill_tree_sync, child_pid) is True
            assert await _wait_dead(child_pid)


@pytest.mark.asyncio
async def test_execute_argv_host_runs_without_a_shell(tmp_path):
    # If a shell were involved, "&" would split the command and the extra
    # args would never reach Python. shell=False passes them as literal args.
    argv = [
        sys.executable, "-c", "import sys; print(len(sys.argv))",
        "a b", "&", "echo pwned",
    ]
    result = await host.execute_argv_host(argv, root=tmp_path, timeout=10)
    assert result["stdout"].strip() == "4"
    assert result["exit_code"] == 0
    assert result["executor"] == "host"
    assert result["sandboxed"] is False
    assert "pwned" not in result["stdout"]


@pytest.mark.asyncio
async def test_execute_argv_host_honours_output_limit(tmp_path):
    argv = [sys.executable, "-c", "print('z' * 5000)"]
    result = await host.execute_argv_host(
        argv, root=tmp_path, timeout=10, output_limit=100
    )
    assert result["exit_code"] == 0
    assert result["output_truncated"] is True
    assert len(result["stdout"]) <= 100


@pytest.mark.asyncio
async def test_execute_argv_host_rejects_invalid_argv(tmp_path):
    with pytest.raises(ValueError):
        await host.execute_argv_host([], root=tmp_path, timeout=5)
    with pytest.raises(ValueError):
        await host.execute_argv_host([sys.executable, ""], root=tmp_path, timeout=5)
    with pytest.raises(ValueError):
        await host.execute_argv_host([sys.executable, "a\nb"], root=tmp_path, timeout=5)
    with pytest.raises(ValueError):
        await host.execute_argv_host([sys.executable, 1], root=tmp_path, timeout=5)


@pytest.mark.asyncio
async def test_execute_argv_host_reports_missing_binary(tmp_path):
    with pytest.raises(OSError):
        await host.execute_argv_host(
            ["nova-missing-binary-for-tests"], root=tmp_path, timeout=5
        )

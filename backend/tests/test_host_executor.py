import asyncio
import os
import sys

import pytest

from app.core.exec import host


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


@pytest.mark.asyncio
async def test_execute_host_runs_command_and_marks_no_isolation(tmp_path):
    command = f'"{sys.executable}" -c "print(\'host-ok\')"'
    result = await host.execute_host(command, root=tmp_path, timeout=10)
    assert result["stdout"].strip() == "host-ok"
    assert result["exit_code"] == 0
    assert result["sandboxed"] is False
    assert result["isolation"] == "none"
    assert result["executor"] == "host"


@pytest.mark.asyncio
async def test_execute_host_strips_secret_env(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVA_TEST_TOKEN", "must-not-leak")
    command = (
        f'"{sys.executable}" -c '
        f'"import os; print(os.getenv(\'NOVA_TEST_TOKEN\', \'missing\'))"'
    )
    result = await host.execute_host(command, root=tmp_path, timeout=10)
    assert result["stdout"].strip() == "missing"


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
    result = await host.execute_host(command, root=tmp_path, timeout=4)
    assert result["timed_out"] is True
    assert marker.is_file()
    child_pid = int(marker.read_text(encoding="utf-8"))
    for _ in range(50):
        if not host.pid_alive(child_pid):
            break
        await asyncio.sleep(0.1)
    assert not host.pid_alive(child_pid)


@pytest.mark.asyncio
async def test_cancel_host_processes_by_job_id(tmp_path):
    command = f'"{sys.executable}" -c "import time; time.sleep(60)"'
    task = asyncio.create_task(
        host.execute_host(command, root=tmp_path, timeout=30, job_id="job-1", user_id=7)
    )
    for _ in range(50):
        if host._RUNNING.get("job-1"):
            break
        await asyncio.sleep(0.05)
    killed = await host.cancel_host_processes("job-1", 7)
    result = await task
    assert killed == 1
    assert result["timed_out"] is False
    assert result["exit_code"] != 0


@pytest.mark.asyncio
async def test_cancel_host_processes_ignores_other_user(tmp_path):
    command = f'"{sys.executable}" -c "import time; time.sleep(2)"'
    task = asyncio.create_task(
        host.execute_host(command, root=tmp_path, timeout=30, job_id="job-2", user_id=7)
    )
    await asyncio.sleep(0.2)
    assert await host.cancel_host_processes("job-2", 99) == 0
    await task

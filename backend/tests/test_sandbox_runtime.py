"""Sandbox runtime: sanitized workspace and stop/cancel cleanup."""
import asyncio
import shutil
import subprocess
import threading
from pathlib import Path

import pytest

from app.core.sandbox import runtime as rt


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_sanitized_workspace_excludes_secrets(tmp_path):
    _write(tmp_path / "main.py", "print(1)")
    _write(tmp_path / ".env", "TOKEN=secret")
    _write(tmp_path / ".env.local", "TOKEN=secret")
    _write(tmp_path / "credentials.json", '{"token": "secret"}')
    _write(tmp_path / "certs" / "server.pem", "KEY")
    _write(tmp_path / "sub" / ".env.production", "TOKEN=secret")
    _write(tmp_path / "node_modules" / "lib.js", "x")
    _write(tmp_path / ".git" / "HEAD", "ref: refs/heads/main")
    _write(tmp_path / ".git" / "config",
           '[remote "origin"]\n\turl = https://user:tok3n@example.com/repo.git\n')

    copy = Path(rt._copy_sanitized_workspace(str(tmp_path), include_git=True))
    try:
        assert (copy / "main.py").is_file()
        assert not (copy / ".env").exists()
        assert not (copy / ".env.local").exists()
        assert not (copy / "credentials.json").exists()
        assert not (copy / "certs" / "server.pem").exists()
        assert not (copy / "sub" / ".env.production").exists()
        assert not (copy / "node_modules").exists()
        assert (copy / ".git" / "HEAD").is_file()
        assert "tok3n" not in (copy / ".git" / "config").read_text(encoding="utf-8")
    finally:
        shutil.rmtree(copy, ignore_errors=True)


def test_sanitized_workspace_can_exclude_git(tmp_path):
    _write(tmp_path / "main.py", "print(1)")
    _write(tmp_path / ".git" / "HEAD", "ref: refs/heads/main")

    copy = Path(rt._copy_sanitized_workspace(str(tmp_path), include_git=False))
    try:
        assert (copy / "main.py").is_file()
        assert not (copy / ".git").exists()
    finally:
        shutil.rmtree(copy, ignore_errors=True)


@pytest.mark.asyncio
async def test_cancel_kills_container(monkeypatch):
    async def fake_status():
        return {"available": True}

    release = threading.Event()

    def fake_run(cmd, stdin_bytes, timeout):
        release.wait(10)
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    killed: list[str] = []

    async def fake_kill(container_name: str):
        killed.append(container_name)

    monkeypatch.setattr(rt, "sandbox_status", fake_status)
    monkeypatch.setattr(rt, "_run_docker", fake_run)
    monkeypatch.setattr(rt, "_kill_container", fake_kill)

    task = asyncio.create_task(rt.execute(files={"main.py": "print(1)"}, command="true"))
    try:
        await asyncio.sleep(0.1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert killed and killed[0].startswith("nova-sbx-")
    finally:
        release.set()


def test_secret_masks_cover_files_dirs_and_git_config(tmp_path, monkeypatch):
    monkeypatch.setattr(rt, "_sandbox_tmp_root", lambda: str(tmp_path))
    _write(tmp_path / "main.py", "print(1)")
    _write(tmp_path / ".env", "TOKEN=secret")
    _write(tmp_path / "credentials.json", '{"token": "secret"}')
    _write(tmp_path / ".ssh" / "id_rsa", "KEY")
    _write(tmp_path / "sub" / ".env.local", "TOKEN=secret")
    _write(tmp_path / ".git" / "config",
           '[remote "origin"]\n\turl = https://user:tok3n@example.com/repo.git\n')

    masks, mask_tmp = rt._build_secret_masks(str(tmp_path))
    try:
        rels = {rel for _, rel in masks}
        assert {".env", "credentials.json", ".ssh", "sub/.env.local", ".git/config"} <= rels
        assert "main.py" not in rels
        config_source = next(source for source, rel in masks if rel == ".git/config")
        assert "tok3n" not in Path(config_source).read_text(encoding="utf-8")
    finally:
        shutil.rmtree(mask_tmp, ignore_errors=True)


def test_host_visible_path_translates_self_mounts(tmp_path, monkeypatch):
    container = tmp_path / "app" / "data"
    host = tmp_path / "host" / "data"
    monkeypatch.setattr(rt, "_self_mounts", lambda: {str(container): str(host)})
    monkeypatch.setattr(rt.settings, "sandbox_host_data_dir", "")

    target = container / "users" / "1" / "repos" / "r1"
    assert rt._host_visible_path(str(target)) == str(host / "users/1/repos/r1")
    outside = tmp_path / "elsewhere" / "file"
    assert rt._host_visible_path(str(outside)) == str(outside)


def test_host_visible_path_uses_explicit_mapping(tmp_path, monkeypatch):
    data_root = tmp_path / "data"
    user_dir = data_root / "users"
    host_root = tmp_path / "host_data"
    monkeypatch.setattr(rt.settings, "user_data_dir", str(user_dir))
    monkeypatch.setattr(rt.settings, "sandbox_host_data_dir", str(host_root))
    assert rt._host_visible_path(str(user_dir / "1" / "repos" / "r1")) == \
        str(host_root / "users/1/repos/r1")


@pytest.mark.asyncio
async def test_execute_mounts_secret_masks(monkeypatch, tmp_path):
    monkeypatch.setattr(rt, "_sandbox_tmp_root", lambda: str(tmp_path))
    monkeypatch.setattr(rt, "_in_container", lambda: False)
    _write(tmp_path / "repo" / "main.py", "print(1)")
    _write(tmp_path / "repo" / ".env", "TOKEN=secret")
    captured: list[str] = []

    async def fake_status():
        return {"available": True}

    def fake_run(cmd, stdin_bytes, timeout):
        captured.extend(cmd)
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr(rt, "sandbox_status", fake_status)
    monkeypatch.setattr(rt, "_run_docker", fake_run)

    result = await rt.execute(
        files={}, command="true", workspace_dir=str(tmp_path / "repo"),
        mask_secrets=True,
    )
    assert result["exit_code"] == 0
    mounts = [
        captured[i + 1] for i, item in enumerate(captured)
        if item == "-v" and i + 1 < len(captured)
    ]
    assert any(mount.endswith(":/workspace/.env:ro") for mount in mounts)
    workspace_index = next(i for i, m in enumerate(mounts) if m.endswith(":/workspace:rw"))
    mask_index = next(i for i, m in enumerate(mounts) if m.endswith(":/workspace/.env:ro"))
    assert workspace_index < mask_index  # parent must mount before child masks


def test_streaming_runner_forwards_output():
    import sys

    chunks: list[tuple[str, str]] = []
    proc, timed_out = rt._run_docker_streaming(
        [sys.executable, "-u", "-c",
         "import sys; print('out-line'); print('err-line', file=sys.stderr)"],
        None, 15, lambda stream, text: chunks.append((stream, text)),
    )
    assert not timed_out
    assert proc.returncode == 0
    assert "out-line" in proc.stdout.decode()
    assert "err-line" in proc.stderr.decode()
    assert any(stream == "stdout" and "out-line" in text for stream, text in chunks)
    assert any(stream == "stderr" and "err-line" in text for stream, text in chunks)


def test_streaming_runner_times_out():
    import sys

    proc, timed_out = rt._run_docker_streaming(
        [sys.executable, "-c", "import time; time.sleep(5)"],
        None, 0.5, lambda *_: None,
    )
    assert timed_out
    assert proc.returncode != 0

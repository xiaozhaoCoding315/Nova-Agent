import os
import shutil
import subprocess
from pathlib import Path

import pytest

from app.config import settings
from app.core.indexing import pipeline
from app.core.indexing.walker import iter_local_project_files
from app.local.projects import register_local_project, validate_local_project_path


def test_validate_local_project_accepts_directory_with_spaces(tmp_path):
    project = tmp_path / "My Project"
    project.mkdir()
    assert validate_local_project_path(str(project), tmp_path / "NovaData") == project.resolve()


def test_validate_local_project_rejects_relative_path(tmp_path):
    with pytest.raises(ValueError, match="绝对路径"):
        validate_local_project_path("relative/project", tmp_path / "NovaData")


def test_validate_local_project_rejects_unc(tmp_path):
    with pytest.raises(ValueError, match="UNC"):
        validate_local_project_path(r"\\server\share\repo", tmp_path / "NovaData")


def test_validate_local_project_rejects_data_dir(tmp_path):
    data = tmp_path / "NovaData"
    project = data / "project"
    project.mkdir(parents=True)
    with pytest.raises(ValueError, match="数据目录"):
        validate_local_project_path(str(project), data)


def test_validate_local_project_rejects_missing_and_file(tmp_path):
    with pytest.raises(ValueError, match="不存在"):
        validate_local_project_path(str(tmp_path / "missing"), tmp_path / "NovaData")
    file_path = tmp_path / "a.py"
    file_path.write_text("print(1)", encoding="utf-8")
    with pytest.raises(ValueError, match="目录"):
        validate_local_project_path(str(file_path), tmp_path / "NovaData")


def test_validate_local_project_rejects_filesystem_root(tmp_path):
    with pytest.raises(ValueError, match="根目录"):
        validate_local_project_path(str(Path(tmp_path.anchor)), tmp_path / "NovaData")


@pytest.mark.asyncio
async def test_register_local_project_creates_and_indexes(monkeypatch, tmp_path):
    project = tmp_path / "repo"
    project.mkdir()
    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(settings, "nova_data_dir", str(tmp_path / "NovaData"))

    async def no_existing(sql, params):
        return []

    async def fake_create(user_id, name, root_path, repo_id):
        return {"id": repo_id, "name": name, "origin": "local", "root_path": root_path}

    enqueued: list[tuple] = []

    async def fake_enqueue(repo_id, **kwargs):
        enqueued.append((repo_id, kwargs))
        return "job-1"

    async def fake_audit(*args, **kwargs):
        return None

    monkeypatch.setattr("app.local.projects.query", no_existing)
    monkeypatch.setattr("app.local.projects.create_local_repo_row", fake_create)
    monkeypatch.setattr("app.local.projects.enqueue_index", fake_enqueue)
    monkeypatch.setattr("app.local.projects.log_audit", fake_audit)
    repo = await register_local_project({"id": 1}, str(project))
    assert repo["origin"] == "local"
    assert enqueued and enqueued[0][1]["user_id"] == 1


@pytest.mark.asyncio
async def test_delete_local_repo_never_removes_project_files(monkeypatch, tmp_path):
    project = tmp_path / "repo"
    project.mkdir()
    removed: list[Path] = []
    monkeypatch.setattr(settings, "nova_mode", "local")

    async def fake_get(repo_id, user_id):
        return {"id": repo_id, "user_id": user_id, "origin": "local", "root_path": str(project)}

    async def fake_execute(sql, params):
        return []

    monkeypatch.setattr(pipeline, "get_repo", fake_get)
    monkeypatch.setattr(pipeline, "execute", fake_execute)
    monkeypatch.setattr(pipeline.shutil, "rmtree", lambda path, **kwargs: removed.append(Path(path)))
    monkeypatch.setattr(
        "app.core.deploy.service.cleanup_repo_resources",
        lambda *args, **kwargs: _async_none(),
    )
    assert await pipeline.delete_repo("00000000-0000-0000-0000-000000000001", 1) is True
    assert removed == []
    assert project.is_dir()


async def _async_none():
    return None


def _git_available() -> bool:
    return shutil.which("git") is not None


@pytest.mark.skipif(not _git_available(), reason="git executable not available")
def test_iter_local_project_files_respects_gitignore(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".gitignore").write_text("ignored.py\n", encoding="utf-8")
    (tmp_path / "keep.py").write_text("print('keep')", encoding="utf-8")
    (tmp_path / "ignored.py").write_text("print('ignored')", encoding="utf-8")
    paths = [rel for rel, _abspath, _size in iter_local_project_files(str(tmp_path), 100_000)]
    assert "keep.py" in paths
    assert "ignored.py" not in paths


def test_iter_local_project_files_falls_back_to_walk(tmp_path, monkeypatch):
    (tmp_path / "a.py").write_text("print('a')", encoding="utf-8")
    monkeypatch.setattr("app.core.indexing.walker._git_listed_files", lambda root: None)
    paths = [rel for rel, _abspath, _size in iter_local_project_files(str(tmp_path), 100_000)]
    assert paths == ["a.py"]


def test_iter_local_project_files_skips_symlink_escape(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("print('outside')", encoding="utf-8")
    link = root / "link.py"
    try:
        os.symlink(outside, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation not permitted on this platform")
    monkeypatch.setattr(
        "app.core.indexing.walker._git_listed_files", lambda root: ["link.py"]
    )
    paths = [rel for rel, _abspath, _size in iter_local_project_files(str(root), 100_000)]
    assert paths == []

import os
import shutil
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.config import settings
from app.core.indexing import pipeline, walker
from app.core.indexing.walker import (
    iter_local_project_files,
    iter_local_project_files_excluding,
)
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


def test_validate_local_project_rejects_data_root_ancestor(tmp_path):
    # The data root lives inside the proposed project: registering it would
    # index Nova's own data (nova-config.json / secretKey) as project files.
    data = tmp_path / "NovaData"
    (data / "users").mkdir(parents=True)
    (data / "nova-config.json").write_text('{"secretKey": "..."}', encoding="utf-8")
    with pytest.raises(ValueError, match="数据目录") as exc:
        validate_local_project_path(str(tmp_path), data)
    assert "NovaData" in str(exc.value)


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


@pytest.mark.asyncio
async def test_delete_local_repo_skips_preview_cleanup(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "nova_mode", "local")
    cleanup = AsyncMock(return_value={})

    async def fake_get(repo_id, user_id):
        return {"id": repo_id, "user_id": user_id, "origin": "local", "root_path": str(tmp_path)}

    async def fake_execute(sql, params):
        return []

    monkeypatch.setattr(pipeline, "get_repo", fake_get)
    monkeypatch.setattr(pipeline, "execute", fake_execute)
    monkeypatch.setattr("app.core.deploy.service.cleanup_repo_resources", cleanup)

    assert await pipeline.delete_repo("00000000-0000-0000-0000-000000000001", 1) is True
    cleanup.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_server_repo_runs_preview_cleanup(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "nova_mode", "server")
    cleanup = AsyncMock(return_value={})
    removed: list[Path] = []

    async def fake_get(repo_id, user_id):
        return {"id": repo_id, "user_id": user_id, "origin": "upload", "root_path": str(tmp_path)}

    async def fake_execute(sql, params):
        return []

    monkeypatch.setattr(pipeline, "get_repo", fake_get)
    monkeypatch.setattr(pipeline, "execute", fake_execute)
    monkeypatch.setattr(pipeline.shutil, "rmtree", lambda path, **kwargs: removed.append(Path(path)))
    monkeypatch.setattr("app.core.deploy.service.cleanup_repo_resources", cleanup)
    monkeypatch.setattr("app.db.qdrant.delete_repo_points", AsyncMock(return_value=None))

    repo_id = "00000000-0000-0000-0000-000000000001"
    assert await pipeline.delete_repo(repo_id, 1) is True
    cleanup.assert_awaited_once_with(repo_id, 1)


def _git_available() -> bool:
    return shutil.which("git") is not None


def _create_dir_link(link: Path, target: Path) -> None:
    """Create a directory junction (Windows) or symlink; skip only if impossible."""
    if os.name == "nt":
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            reason = (result.stderr or result.stdout or "").strip()
            pytest.skip(f"directory junction creation failed: {reason or result.returncode}")
        return
    try:
        os.symlink(target, link, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"directory symlink creation failed: {exc}")


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


def test_iter_local_project_files_fallback_skips_junction_escape(tmp_path, monkeypatch):
    """No-git folder: a junction pointing outside must never be traversed."""
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.py").write_text("print('outside')", encoding="utf-8")
    (project / "inside.py").write_text("print('inside')", encoding="utf-8")
    _create_dir_link(project / "esc", outside)
    monkeypatch.setattr(walker, "_git_listed_files", lambda root: None)

    files = list(iter_local_project_files(str(project), 100_000))

    assert [rel for rel, _abspath, _size in files] == ["inside.py"]
    root_resolved = project.resolve()
    assert all(Path(abspath).is_relative_to(root_resolved) for _, abspath, _ in files)


def test_iter_local_project_files_git_listing_skips_junction_escape(tmp_path, monkeypatch):
    """The git-listed branch must keep its containment check for junctions."""
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.py").write_text("print('outside')", encoding="utf-8")
    _create_dir_link(project / "esc", outside)
    monkeypatch.setattr(
        walker, "_git_listed_files", lambda root: ["esc/secret.py"]
    )

    assert list(iter_local_project_files(str(project), 100_000)) == []


def test_iter_local_project_files_keeps_in_root_junction(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    source = project / "src"
    source.mkdir()
    (source / "a.py").write_text("print('a')", encoding="utf-8")
    _create_dir_link(project / "alias", source)
    monkeypatch.setattr(walker, "_git_listed_files", lambda root: None)

    paths = [rel for rel, _abspath, _size in iter_local_project_files(str(project), 100_000)]

    assert len(paths) == 1
    assert paths[0].endswith("a.py")


def test_iter_local_project_files_excluding_prunes_data_root(tmp_path, monkeypatch):
    project = tmp_path / "project"
    data = project / "NovaData"
    data.mkdir(parents=True)
    (data / "nova-config.json").write_text('{"secretKey": "..."}', encoding="utf-8")
    (project / "app.py").write_text("print(1)", encoding="utf-8")
    monkeypatch.setattr(walker, "_git_listed_files", lambda root: None)

    files = list(
        iter_local_project_files_excluding(str(project), 100_000, (data,))
    )

    assert [rel for rel, _abspath, _size in files] == ["app.py"]


@pytest.mark.asyncio
async def test_index_repo_local_missing_root_marks_failed(monkeypatch, tmp_path):
    missing = tmp_path / "gone"
    statuses: list[tuple[str, str | None]] = []

    async def fake_get_repo(repo_id, user_id=None):
        return {
            "id": repo_id,
            "user_id": 1,
            "name": "gone",
            "origin": "local",
            "root_path": str(missing),
        }

    async def fake_set_status(repo_id, status, error=None):
        statuses.append((status, error))

    async def fake_execute(sql, params):
        return []

    monkeypatch.setattr(pipeline, "get_repo", fake_get_repo)
    monkeypatch.setattr(pipeline, "set_status", fake_set_status)
    monkeypatch.setattr(pipeline, "execute", fake_execute)

    await pipeline.index_repo("00000000-0000-0000-0000-000000000001")

    assert statuses == [("failed", f"本地项目目录不存在或已移动：{missing}")]
    assert not missing.exists()


def _api_client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.v1 import repos as repos_api
    from app.core.security.auth import get_current_user

    app = FastAPI()
    app.include_router(repos_api.router)
    app.dependency_overrides[get_current_user] = lambda: {
        "id": 1,
        "username": "local",
        "role": "local",
    }
    return TestClient(app)


def test_api_local_endpoint_404_outside_local_mode(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "nova_mode", "server")
    project = tmp_path / "project"
    project.mkdir()

    response = _api_client().post("/repos/local", json={"path": str(project)})

    assert response.status_code == 404
    assert "本地模式" in response.json()["detail"]


def test_api_local_endpoint_400_for_invalid_path(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(settings, "nova_data_dir", str(tmp_path / "NovaData"))

    response = _api_client().post(
        "/repos/local", json={"path": str(tmp_path / "missing")}
    )

    assert response.status_code == 400
    assert "不存在" in response.json()["detail"]


def test_api_local_endpoint_503_without_data_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(settings, "nova_data_dir", "")
    project = tmp_path / "project"
    project.mkdir()

    response = _api_client().post("/repos/local", json={"path": str(project)})

    assert response.status_code == 503
    assert "NOVA_DATA_DIR" in response.json()["detail"]

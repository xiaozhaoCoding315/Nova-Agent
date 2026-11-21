"""Per-user workspace registry, including local custom roots."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.config import settings
from app.core.documents import store


@pytest.fixture()
def user_root(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "user_data_dir", str(tmp_path / "data"))
    return tmp_path


def test_default_workspace_is_registered_and_listed(user_root: Path):
    workspace = store.create_user_workspace(1, title="课程报告")
    assert workspace.root.is_relative_to(store.documents_root(1))
    items = store.list_workspaces(1)
    assert [item["title"] for item in items] == ["课程报告"]
    assert store.get_workspace(1, workspace.id).root == workspace.root


def test_custom_root_requires_local_mode_flag(user_root: Path):
    custom = user_root / "Documents" / "thesis"
    with pytest.raises(store.WorkspaceError):
        store.create_user_workspace(1, title="论文", root=str(custom))
    assert not custom.exists()


def test_custom_root_is_registered_and_never_deleted(user_root: Path):
    custom = user_root / "Documents" / "report"
    workspace = store.create_user_workspace(
        1, title="本地报告", root=str(custom), allow_custom_root=True,
    )
    assert (custom / "manuscripts" / "main.md").exists()
    assert store.get_workspace(1, workspace.id).root == custom.resolve()

    assert store.remove_workspace(1, workspace.id) is True
    assert custom.exists()
    assert store.list_workspaces(1) == []


def test_default_workspace_files_are_deleted_on_remove(user_root: Path):
    workspace = store.create_user_workspace(1, title="报告")
    assert workspace.root.exists()
    assert store.remove_workspace(1, workspace.id) is True
    assert not workspace.root.exists()


def test_unknown_workspace_is_not_found(user_root: Path):
    with pytest.raises(store.WorkspaceNotFound):
        store.get_workspace(1, "not-a-real-id")
    with pytest.raises(store.WorkspaceNotFound):
        store.get_workspace(1, "../../etc")
    assert store.remove_workspace(1, "deadbeefdeadbeef") is False


def test_other_users_cannot_see_workspaces(user_root: Path):
    workspace = store.create_user_workspace(1, title="我的报告")
    assert store.list_workspaces(2) == []
    with pytest.raises(store.WorkspaceNotFound):
        store.get_workspace(2, workspace.id)

"""Per-user registry of document workspaces.

The registry is a small JSON file next to the default workspace folders.  It
only maps ids to roots; every fact about a document still lives in its own
directory.  Custom roots are allowed only when the caller says so (the local
desktop mode); server mode keeps workspaces under the user's storage root.
"""
from __future__ import annotations

import json
import re
import shutil
import threading
import uuid
from pathlib import Path

from app.config import settings
from app.core.documents.workspace import (
    Workspace,
    WorkspaceError,
    WorkspaceNotFound,
    create_workspace,
    open_workspace,
)

REGISTRY_SCHEMA = "document-registry-1.0"
_WORKSPACE_ID = re.compile(r"^[a-f0-9]{8,64}$")
_LOCK = threading.Lock()


def documents_root(user_id: int) -> Path:
    return Path(settings.user_data_dir) / str(user_id) / "documents"


def _registry_path(user_id: int) -> Path:
    return documents_root(user_id) / "registry.json"


def _read_registry(user_id: int) -> dict:
    path = _registry_path(user_id)
    if not path.exists():
        return {"schema": REGISTRY_SCHEMA, "workspaces": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise WorkspaceError("文档工作区注册表损坏") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("workspaces"), dict):
        raise WorkspaceError("文档工作区注册表格式不对")
    return payload


def _write_registry(user_id: int, payload: dict) -> None:
    import os
    import tempfile

    path = _registry_path(user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".registry.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def _ensure_id(workspace_id: str) -> str:
    value = (workspace_id or "").strip().lower()
    if not _WORKSPACE_ID.match(value):
        raise WorkspaceNotFound("文档工作区不存在")
    return value


def _register(user_id: int, workspace: Workspace) -> None:
    with _LOCK:
        payload = _read_registry(user_id)
        payload["workspaces"][workspace.id] = {
            "root": str(workspace.root),
            "title": workspace.title,
            "kind": workspace.kind,
            "created_at": workspace.created_at,
        }
        _write_registry(user_id, payload)


def create_user_workspace(user_id: int, *, title: str, kind: str = "report",
                          root: str | None = None,
                          allow_custom_root: bool = False) -> Workspace:
    if root and not allow_custom_root:
        raise WorkspaceError("服务器模式不支持自选目录；请使用默认工作区")
    workspace_id = uuid.uuid4().hex
    if root:
        target = Path(root).expanduser()
        if not target.is_absolute():
            raise WorkspaceError("本地工作目录必须是绝对路径")
    else:
        target = documents_root(user_id) / workspace_id
    workspace = create_workspace(target, title=title, kind=kind, workspace_id=workspace_id)
    _register(user_id, workspace)
    return workspace


def list_workspaces(user_id: int) -> list[dict]:
    payload = _read_registry(user_id)
    items: list[dict] = []
    for entry in payload["workspaces"].values():
        root = Path(str((entry or {}).get("root") or ""))
        try:
            workspace = open_workspace(root)
        except (WorkspaceError, OSError):
            # A temporarily unmounted drive must not erase the registry entry.
            continue
        items.append({**workspace.to_dict(), "root": str(workspace.root)})
    return sorted(items, key=lambda item: item.get("created_at") or "", reverse=True)


def get_workspace(user_id: int, workspace_id: str) -> Workspace:
    workspace_id = _ensure_id(workspace_id)
    entry = (_read_registry(user_id).get("workspaces") or {}).get(workspace_id)
    if not isinstance(entry, dict) or not entry.get("root"):
        raise WorkspaceNotFound("文档工作区不存在")
    workspace = open_workspace(Path(str(entry["root"])))
    if workspace.id != workspace_id:
        raise WorkspaceError("工作区目录与注册表不一致")
    return workspace


def remove_workspace(user_id: int, workspace_id: str) -> bool:
    """Unregister a workspace; delete files only inside Nova's own storage."""
    workspace_id = _ensure_id(workspace_id)
    with _LOCK:
        payload = _read_registry(user_id)
        entry = payload["workspaces"].pop(workspace_id, None)
        if not entry:
            return False
        _write_registry(user_id, payload)
    root = Path(str(entry.get("root") or ""))
    try:
        root.resolve().relative_to(documents_root(user_id).resolve())
    except ValueError:
        return True  # custom user directory: leave the files alone
    shutil.rmtree(root, ignore_errors=True)
    return True


__all__ = [
    "REGISTRY_SCHEMA", "create_user_workspace", "documents_root",
    "get_workspace", "list_workspaces", "remove_workspace",
]

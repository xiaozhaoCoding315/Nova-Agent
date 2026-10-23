"""Workspace editing: stage → approve/reject → apply → revert (snapshots).

Snapshots are the pre-write contents stored on the edit row, so every applied
change can be reverted without Git.
"""
import difflib
import json
import uuid
from pathlib import Path

import structlog

from app.core.conflicts import ConflictError
from app.core.indexing.pipeline import get_repo
from app.core.security.paths import (
    is_secret_path, resolve_repo_path, try_normalize_relpath,
)
from app.core.security.test_guard import assert_changes_preserve_tests
from app.db import execute, query

logger = structlog.get_logger()

MAX_FILES = 20
MAX_FILE_CHARS = 120_000
MAX_TOTAL_CHARS = 300_000

PERMISSION_MODES = ("readonly", "ask", "auto")


def validate_changes(files: dict) -> dict[str, str]:
    """Path-safe, bounded file map."""
    changes: dict[str, str] = {}
    total = 0
    for raw_path, content in (files or {}).items():
        path = try_normalize_relpath(raw_path)
        if not path or is_secret_path(path):
            continue
        if not isinstance(content, str) or not content.strip():
            continue
        content = content[:MAX_FILE_CHARS]
        total += len(content)
        if len(changes) >= MAX_FILES or total > MAX_TOTAL_CHARS:
            break
        changes[path] = content
    return changes


def _safe_target(root: Path, path: str) -> Path:
    return resolve_repo_path(root, path)


def build_diff(base: dict[str, str | None], changes: dict[str, str]) -> str:
    parts: list[str] = []
    for path, content in changes.items():
        old = base.get(path) or ""
        diff = difflib.unified_diff(
            old.splitlines(),
            content.splitlines(),
            fromfile=f"a/{path}" if old else "/dev/null",
            tofile=f"b/{path}",
            lineterm="",
        )
        parts.append("\n".join(diff))
    return "\n\n".join(p for p in parts if p.strip())


def _read_current(root: Path, changes: dict[str, str]) -> dict[str, str | None]:
    base: dict[str, str | None] = {}
    for path in changes:
        target = _safe_target(root, path)
        base[path] = target.read_text(encoding="utf-8", errors="replace") if target.is_file() else None
    return base


def _write_files(root: Path, files: dict[str, str]) -> list[str]:
    written: list[str] = []
    for path, content in files.items():
        target = _safe_target(root, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        written.append(path)
    return written


async def create_edit(
    user_id: int,
    session_id: str | None,
    repo_id: str,
    files: dict,
    note: str = "",
    mode: str = "ask",
) -> dict:
    """In auto mode the change is written immediately; otherwise it is staged
    as a pending proposal that the user must approve."""
    repo = await get_repo(repo_id, user_id)
    if not repo:
        raise ValueError("仓库不存在或无权访问")

    for raw_path in (files or {}):
        candidate = try_normalize_relpath(raw_path)
        if candidate and is_secret_path(candidate):
            raise ValueError(f"拒绝写入密钥/凭据文件：{candidate}")

    changes = validate_changes(files)
    if not changes:
        raise ValueError("没有有效文件内容（检查路径与内容）")

    root = Path(repo["root_path"]).resolve()
    base = _read_current(root, changes)
    assert_changes_preserve_tests(changes, base)
    diff = build_diff(base, changes)
    edit_id = str(uuid.uuid4())
    applied = mode == "auto"

    await execute(
        "INSERT INTO edits (id, user_id, session_id, repo_id, status, files, base_files, diff, note, applied_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            edit_id, user_id, session_id, repo_id,
            "applied" if applied else "pending",
            json.dumps(changes, ensure_ascii=False),
            json.dumps(base, ensure_ascii=False),
            diff, note[:1000],
            "now()" if applied else None,
        ),
    )
    if applied:
        _write_files(root, changes)

    return {
        "id": edit_id,
        "status": "applied" if applied else "pending",
        "staged": not applied,
        "repo_id": repo_id,
        "repo_name": repo["name"],
        "files": list(changes),
        "diff": diff,
        "note": note,
    }


async def get_edit(edit_id: str, user_id: int) -> dict | None:
    rows = await query(
        """
        SELECT e.id, e.status, e.files, e.base_files, e.diff, e.note, e.created_at,
               e.applied_at, e.repo_id, r.name, e.review
        FROM edits e JOIN repos r ON r.id = e.repo_id
        WHERE e.id = %s AND e.user_id = %s
        """,
        (edit_id, user_id),
    )
    if not rows:
        return None
    r = rows[0]
    files = r[2] or {}
    return {
        "id": str(r[0]), "status": r[1], "files": files,
        "file_paths": list(files.keys()), "diff": r[4] or "", "note": r[5] or "",
        "created_at": r[6], "applied_at": r[7],
        "repo_id": str(r[8]), "repo_name": r[9], "review": r[10],
    }


async def apply_edit(edit_id: str, user_id: int) -> dict:
    rows = await query(
        "SELECT id, repo_id, status, files, base_files, session_id FROM edits "
        "WHERE id = %s AND user_id = %s",
        (edit_id, user_id),
    )
    if not rows:
        raise ValueError("修改不存在")
    _, repo_id, status, files, base_files, session_id = rows[0]
    if status != "pending":
        raise ValueError(f"当前状态（{status}）不能批准")
    repo = await get_repo(str(repo_id), user_id)
    if not repo:
        raise ValueError("仓库不存在")
    root = Path(repo["root_path"]).resolve()
    changes = validate_changes(files or {})
    if not changes:
        raise ValueError("没有可应用的文件内容")
    base = _read_current(root, changes)
    for path, expected in (base_files or {}).items():
        if path in base and base[path] != expected:
            raise ConflictError(f"文件在提案生成后已被修改：{path}，请重新读取并生成修改")
    assert_changes_preserve_tests(changes, base)
    written = _write_files(root, changes)
    await execute(
        "UPDATE edits SET status = 'applied', applied_at = now() WHERE id = %s", (edit_id,)
    )
    from app.core.git_ops.service import auto_commit
    commit_hash = await auto_commit(root, f"edit: apply {edit_id[:8]}")
    return {
        "applied": written, "repo_id": str(repo_id),
        "session_id": str(session_id) if session_id else None,
        "commit": commit_hash,
    }


async def reject_edit(edit_id: str, user_id: int) -> dict:
    rows = await query(
        "SELECT status, session_id, repo_id FROM edits WHERE id = %s AND user_id = %s",
        (edit_id, user_id),
    )
    if not rows:
        raise ValueError("修改不存在")
    if rows[0][0] != "pending":
        raise ValueError("只有待审批的修改才能拒绝")
    await execute("UPDATE edits SET status = 'rejected' WHERE id = %s", (edit_id,))
    return {
        "session_id": str(rows[0][1]) if rows[0][1] else None,
        "repo_id": str(rows[0][2]),
    }


async def revert_edit(edit_id: str, user_id: int) -> dict:
    """Restore the snapshot taken before the edit was applied."""
    rows = await query(
        "SELECT id, repo_id, status, base_files, files, session_id FROM edits "
        "WHERE id = %s AND user_id = %s",
        (edit_id, user_id),
    )
    if not rows:
        raise ValueError("修改不存在")
    _, repo_id, status, base_files, files, session_id = rows[0]
    if status != "applied":
        raise ValueError("只有已应用的修改才能撤销")
    repo = await get_repo(str(repo_id), user_id)
    if not repo:
        raise ValueError("仓库不存在")

    root = Path(repo["root_path"]).resolve()
    current = _read_current(root, files or {})
    for path, expected in (files or {}).items():
        if path in current and current[path] != expected:
            raise ConflictError(f"文件在应用后被再次修改：{path}，撤销可能覆盖新改动，已阻止")
    restored: list[str] = []
    removed: list[str] = []
    for path, old in (base_files or {}).items():
        target = _safe_target(root, path)
        if old is None:
            if target.is_file():
                target.unlink()
                removed.append(path)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(old, encoding="utf-8")
            restored.append(path)

    await execute("UPDATE edits SET status = 'reverted' WHERE id = %s", (edit_id,))
    from app.core.git_ops.service import auto_commit
    commit_hash = await auto_commit(root, f"edit: revert {edit_id[:8]}")
    return {
        "restored": restored, "removed": removed, "repo_id": str(repo_id),
        "session_id": str(session_id) if session_id else None,
        "commit": commit_hash,
    }
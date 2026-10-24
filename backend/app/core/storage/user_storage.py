"""Per-user storage roots and uploaded-file persistence."""
import asyncio
import hashlib
import mimetypes
import re
import shutil
import uuid
from pathlib import Path

import structlog

from app.config import settings
from app.db import execute, query

logger = structlog.get_logger()

CHUNK = 1024 * 1024
TEXT_SUFFIXES = {
    ".txt", ".md", ".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".yaml", ".yml",
    ".toml", ".ini", ".cfg", ".html", ".css", ".sql", ".sh", ".java", ".go", ".rs",
    ".c", ".cpp", ".h", ".xml", ".csv", ".log",
}
FILE_COLUMNS = (
    "id, user_id, repo_id, session_id, filename, mime, size, sha256, purpose, created_at"
)


def user_root(user_id: int) -> Path:
    return Path(settings.user_data_dir) / str(user_id)


def repo_container(user_id: int, repo_id: str) -> Path:
    return user_root(user_id) / "repos" / str(repo_id)


def uploads_root(user_id: int) -> Path:
    return user_root(user_id) / "uploads"


def sanitize_filename(filename: str) -> str:
    name = Path((filename or "file").replace("\\", "/")).name
    name = re.sub(r"[\x00-\x1f<>:\"|?*]", "_", name).strip().strip(".")
    return (name or "file")[:200]


def _row_to_file(row: tuple) -> dict:
    return {
        "id": str(row[0]), "user_id": row[1],
        "repo_id": str(row[2]) if row[2] else None,
        "session_id": str(row[3]) if row[3] else None,
        "filename": row[4], "mime": row[5] or "application/octet-stream",
        "size": int(row[6] or 0), "sha256": row[7], "purpose": row[8],
        "created_at": row[9],
    }


async def save_upload(
    user_id: int,
    stream,
    *,
    filename: str,
    mime: str | None = None,
    repo_id: str | None = None,
    session_id: str | None = None,
    purpose: str = "attachment",
) -> dict:
    name = sanitize_filename(filename)
    suffix = Path(name).suffix[:20]
    file_id = str(uuid.uuid4())
    root = uploads_root(user_id)
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{file_id}{suffix}"
    max_bytes = settings.attachment_max_mb * 1024 * 1024
    total = 0
    digest = hashlib.sha256()

    try:
        with open(path, "wb") as out:
            while chunk := await stream.read(CHUNK):
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError(f"文件超过上限（{settings.attachment_max_mb}MB）")
                digest.update(chunk)
                out.write(chunk)
        rows = await execute(
            "INSERT INTO user_files "
            "(id, user_id, repo_id, session_id, filename, mime, size, sha256, storage_path, purpose) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            f"RETURNING {FILE_COLUMNS}",
            (
                file_id, user_id, repo_id, session_id, name,
                mime or mimetypes.guess_type(name)[0] or "application/octet-stream",
                total, digest.hexdigest(), str(path), purpose,
            ),
        )
    except Exception:
        path.unlink(missing_ok=True)
        raise
    if not rows:
        path.unlink(missing_ok=True)
        raise RuntimeError("保存文件失败")
    return _row_to_file(rows[0])


async def list_files(
    user_id: int,
    *,
    repo_id: str | None = None,
    session_id: str | None = None,
    limit: int = 100,
) -> list[dict]:
    clauses = ["user_id = %s"]
    params: list = [user_id]
    if repo_id:
        clauses.append("repo_id = %s")
        params.append(repo_id)
    if session_id:
        clauses.append("session_id = %s")
        params.append(session_id)
    params.append(limit)
    rows = await query(
        f"SELECT {FILE_COLUMNS} FROM user_files WHERE {' AND '.join(clauses)} "
        "ORDER BY created_at DESC LIMIT %s",
        tuple(params),
    )
    return [_row_to_file(row) for row in rows]


async def get_file(file_id: str, user_id: int) -> dict | None:
    rows = await query(
        f"SELECT {FILE_COLUMNS}, storage_path FROM user_files "
        "WHERE id = %s AND user_id = %s",
        (file_id, user_id),
    )
    if not rows:
        return None
    file = _row_to_file(rows[0][:10])
    file["storage_path"] = rows[0][10]
    return file


async def delete_file(file_id: str, user_id: int) -> bool:
    file = await get_file(file_id, user_id)
    if not file:
        return False
    Path(file["storage_path"]).unlink(missing_ok=True)
    await execute("DELETE FROM user_files WHERE id = %s AND user_id = %s", (file_id, user_id))
    return True


async def used_bytes(user_id: int) -> int:
    rows = await query(
        "SELECT COALESCE(SUM(size), 0) FROM user_files WHERE user_id = %s",
        (user_id,),
    )
    return int(rows[0][0]) if rows else 0


def storage_limit_bytes(user: dict) -> int:
    mb = user.get("quota_storage_mb")
    if mb is None:
        mb = settings.guest_storage_mb if user.get("is_guest") else settings.user_storage_mb
    return int(mb) * 1024 * 1024


async def read_text(file_id: str, user_id: int, max_chars: int = 50_000) -> dict:
    file = await get_file(file_id, user_id)
    if not file:
        raise ValueError("附件不存在或无权访问")
    suffix = Path(file["filename"]).suffix.lower()
    if not (file["mime"].startswith("text/") or suffix in TEXT_SUFFIXES):
        raise ValueError("该附件不是可读文本，无法作为代码上下文")
    path = Path(file["storage_path"])
    if not path.exists():
        raise ValueError("附件文件已丢失")
    content = path.read_text(encoding="utf-8", errors="replace")
    return {
        "id": file["id"], "filename": file["filename"], "size": file["size"],
        "content": content[:max_chars],
        "truncated": len(content) > max_chars,
    }


async def cleanup_user_storage(user_id: int) -> None:
    await asyncio.to_thread(shutil.rmtree, user_root(user_id), True)


async def migrate_legacy_repos() -> dict:
    """Move repos from data/repos/<id> to data/users/<uid>/repos/<id>."""
    rows = await query("SELECT id, user_id, root_path FROM repos")
    moved = 0
    updated = 0
    for repo_id, user_id, root_path in rows:
        old_container = Path(settings.repos_dir) / str(repo_id)
        new_container = repo_container(user_id, str(repo_id))
        if new_container.exists():
            continue
        if not old_container.exists():
            continue
        new_container.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(shutil.move, str(old_container), str(new_container))
        moved += 1

        old_root = Path(root_path)
        try:
            relative = old_root.relative_to(old_container)
        except ValueError:
            relative = Path(".")
        new_root = new_container / relative
        if str(new_root) != root_path:
            await execute("UPDATE repos SET root_path = %s WHERE id = %s", (str(new_root), repo_id))
            updated += 1
    if moved or updated:
        logger.info("legacy_repo_storage_migrated", moved=moved, updated=updated)
    return {"moved": moved, "updated": updated}

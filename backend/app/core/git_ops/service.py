"""Git delivery for repo workspaces: init / commit / status / diff /
rollback / export. Also provides auto-commit used by edit/task/builder flows."""
import asyncio
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

import structlog

logger = structlog.get_logger()

GIT_TIMEOUT = 25
_HASH = re.compile(r"^[0-9a-f]{7,40}$")


def git_available() -> bool:
    return shutil.which("git") is not None


def _run_git(root: Path, *args: str, timeout: int = GIT_TIMEOUT) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(root), "-c", "core.quotepath=false", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


async def _git(root: Path, *args: str, timeout: int = GIT_TIMEOUT) -> subprocess.CompletedProcess:
    return await asyncio.to_thread(_run_git, root, *args, timeout=timeout)


def _require_git() -> None:
    if not git_available():
        raise ValueError("服务器未安装 git")


async def status(root: Path) -> dict:
    if not git_available():
        return {"available": False, "initialized": False, "reason": "git not installed", "commits": []}
    if not (Path(root) / ".git").is_dir():
        return {"available": True, "initialized": False, "dirty": False, "commits": []}

    branch = (await _git(root, "rev-parse", "--abbrev-ref", "HEAD")).stdout.strip()
    dirty_out = (await _git(root, "status", "--porcelain")).stdout.strip()
    log = await _git(root, "log", "-10", "--pretty=format:%H%x1f%s%x1f%ci%x1e")
    commits = []
    for record in log.stdout.split("\x1e"):
        parts = record.strip().split("\x1f")
        if len(parts) == 3:
            commits.append({"hash": parts[0], "message": parts[1], "date": parts[2]})
    return {
        "available": True,
        "initialized": True,
        "branch": branch or "main",
        "dirty": bool(dirty_out),
        "changed_files": len(dirty_out.splitlines()) if dirty_out else 0,
        "commits": commits,
    }


async def init_repo(root: Path) -> dict:
    _require_git()
    root = Path(root)
    if not (root / ".git").is_dir():
        result = await _git(root, "init", "-b", "main")
        if result.returncode != 0:
            raise ValueError(f"git init 失败：{result.stderr[:300]}")
        await _git(root, "config", "user.email", "nova@local")
        await _git(root, "config", "user.name", "Nova Agent")

    result = await _git(root, "add", "-A")
    if result.returncode != 0:
        raise ValueError(f"git add 失败：{result.stderr[:300]}")
    result = await _git(root, "commit", "-m", "chore: initial workspace snapshot")
    if result.returncode != 0 and "nothing to commit" not in (result.stdout + result.stderr):
        raise ValueError(f"git commit 失败：{(result.stderr or result.stdout)[:300]}")
    return await status(root)


async def commit(root: Path, message: str | None = None) -> dict:
    _require_git()
    root = Path(root)
    if not (root / ".git").is_dir():
        raise ValueError("尚未初始化 Git，请先初始化")
    message = (message or "chore: update workspace").strip()[:200] or "chore: update workspace"
    add = await _git(root, "add", "-A")
    if add.returncode != 0:
        raise ValueError(f"git add 失败：{add.stderr[:300]}")
    result = await _git(root, "commit", "-m", message)
    if result.returncode != 0 and "nothing to commit" not in (result.stdout + result.stderr):
        raise ValueError(f"git commit 失败：{(result.stderr or result.stdout)[:300]}")
    return await status(root)


async def diff(root: Path) -> str:
    root = Path(root)
    if not (root / ".git").is_dir():
        return ""
    unstaged = await _git(root, "diff", "--no-color")
    staged = await _git(root, "diff", "--cached", "--no-color")
    return ((staged.stdout or "") + (unstaged.stdout or ""))[:20_000]


async def rollback(root: Path, commit_hash: str) -> dict:
    _require_git()
    if not _HASH.match(commit_hash or ""):
        raise ValueError("非法提交哈希")
    root = Path(root)
    if not (root / ".git").is_dir():
        raise ValueError("尚未初始化 Git")
    result = await _git(root, "reset", "--hard", commit_hash)
    if result.returncode != 0:
        raise ValueError(f"回滚失败：{(result.stderr or result.stdout)[:300]}")
    return await status(root)


def export_zip(root: Path) -> Path:
    """Zip the workspace (excluding .git and build dirs) into a temp file."""
    root = Path(root)
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    tmp.close()
    skip = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".pytest_cache"}
    with zipfile.ZipFile(tmp.name, "w", zipfile.ZIP_DEFLATED) as archive:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in skip]
            for name in filenames:
                path = Path(dirpath) / name
                try:
                    if path.stat().st_size > 5 * 1024 * 1024:
                        continue
                    archive.write(path, path.relative_to(root))
                except OSError:
                    continue
    return Path(tmp.name)


async def auto_commit(root: Path | str, message: str) -> str | None:
    """Commit after an approved change when the workspace is a git repo.
    Never raises — delivery must not break the primary flow."""
    try:
        if not (Path(root) / ".git").is_dir():
            return None
        info = await commit(Path(root), message)
        commits = info.get("commits") or []
        return commits[0]["hash"] if commits else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("auto_commit_failed", error=str(exc))
        return None


async def prepare_change_branch(root: Path | str, change_id: str) -> dict:
    """Create/check out an isolated branch for one change.

    Refuses to switch when the workspace has uncommitted changes so an
    approved proposal never mixes with the user's in-progress edits.
    """
    root = Path(root)
    if not git_available() or not (root / ".git").is_dir():
        return {"branch": None, "original": None}

    dirty = await _git(root, "status", "--porcelain")
    if dirty.stdout.strip():
        raise ValueError("工作区有未提交改动，请先提交或撤销后再应用变更")

    original = (await _git(root, "rev-parse", "--abbrev-ref", "HEAD")).stdout.strip() or "main"
    branch = f"nova/change-{str(change_id)[:8]}"
    exists = await _git(root, "rev-parse", "--verify", f"refs/heads/{branch}")
    result = (
        await _git(root, "checkout", branch)
        if exists.returncode == 0
        else await _git(root, "checkout", "-b", branch)
    )
    if result.returncode != 0:
        raise ValueError(f"创建变更分支失败：{(result.stderr or result.stdout)[:300]}")
    return {"branch": branch, "original": original}


async def restore_change_branch(
    root: Path | str, original: str | None, *, discard: bool = False
) -> bool:
    """Return to the original branch, optionally discarding partial writes."""
    if not original:
        return False
    root = Path(root)
    if discard:
        await _git(root, "reset", "--hard", "HEAD")
    result = await _git(root, "checkout", original)
    return result.returncode == 0
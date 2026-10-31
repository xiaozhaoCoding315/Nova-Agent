"""Repo acquisition (zip upload / public git clone) and safe file traversal."""
import asyncio
import os
import shutil
import subprocess
import zipfile
from pathlib import Path

import structlog

from app.core.indexing.languages import SKIP_DIRS, is_supported, looks_binary
from app.core.security.paths import is_secret_path

logger = structlog.get_logger()


def safe_extract_zip(zip_path: str, dest: str, max_files: int, max_file_bytes: int) -> int:
    """Extract a zip, rejecting traversal and bounding file count/size."""
    count = 0
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = info.filename.replace("\\", "/")
            parts = [p for p in name.split("/") if p not in ("", ".")]
            if not parts or name.startswith("/") or any(p == ".." for p in parts):
                raise ValueError(f"非法压缩包路径: {info.filename}")
            if count >= max_files:
                raise ValueError(f"文件数超过上限（{max_files}）")
            if info.file_size > max_file_bytes:
                logger.info("zip_skip_oversized", name=name, size=info.file_size)
                continue
            target = Path(dest).joinpath(*parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            count += 1
    if count == 0:
        raise ValueError("压缩包中没有可用文件")
    return count


async def clone_git(url: str, dest: str, timeout: int) -> None:
    """Shallow-clone a public http(s) repo, keeping history for the Git panel."""
    if not (url.startswith("https://") or url.startswith("http://")):
        raise ValueError("仅支持公开的 http(s) 仓库地址")
    authority = url.split("//", 1)[-1].split("/")[0]
    if "@" in authority:
        raise ValueError("不支持带凭证的仓库地址")

    proc = await asyncio.create_subprocess_exec(
        "git", "clone", "--depth", "1", "--single-branch", url, dest,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise ValueError(f"git clone 超时（{timeout}s），仓库过大或网络不可达")
    if proc.returncode != 0:
        raise ValueError(f"git clone 失败：{stderr.decode('utf-8', 'replace')[:300]}")
    # Approvals auto-commit into this workspace; make sure an identity exists.
    for key, value in (("user.email", "nova@local"), ("user.name", "Nova Agent")):
        await asyncio.to_thread(
            subprocess.run,
            ["git", "-C", dest, "config", key, value],
            capture_output=True, timeout=10,
        )
    from app.core.git_ops.service import ensure_secret_excludes
    await asyncio.to_thread(ensure_secret_excludes, Path(dest))


def strip_root_dir(root: str) -> str:
    """Hoist a single top-level directory (common zip layout: repo-main/...)."""
    entries = [e for e in os.listdir(root) if e not in ("__MACOSX",)]
    if len(entries) == 1:
        only = Path(root) / entries[0]
        if only.is_dir():
            return str(only)
    return root


def iter_source_files(root: str, max_file_bytes: int):
    """Yield (relpath, abspath, size) for supported text/code files."""
    root_path = Path(root)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for filename in filenames:
            abspath = Path(dirpath) / filename
            try:
                rel = str(abspath.relative_to(root_path)).replace("\\", "/")
            except ValueError:
                continue
            if not is_supported(rel) or is_secret_path(rel):
                continue
            try:
                size = abspath.stat().st_size
            except OSError:
                continue
            if size == 0 or size > max_file_bytes:
                continue
            if not rel.lower().endswith(".pdf"):
                try:
                    head = abspath.open("rb").read(2048)
                except OSError:
                    continue
                if looks_binary(head):
                    continue
            yield rel, str(abspath), size


def _git_listed_files(root: Path) -> list[str] | None:
    """Tracked + untracked (non-ignored) files. None means fall back to walk."""
    git = shutil.which("git")
    if not git:
        return None
    try:
        result = subprocess.run(
            [
                git, "-C", str(root), "ls-files", "-z",
                "--cached", "--others", "--exclude-standard",
            ],
            capture_output=True, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return [p for p in result.stdout.decode("utf-8", "replace").split("\0") if p]


def _resolve_strict(path: str | Path) -> Path | None:
    """Resolve ``path`` (following reparse points) or return None if it is gone."""
    try:
        return Path(path).resolve(strict=True)
    except OSError:
        return None


def _resolve_excluded(path: str | Path) -> Path | None:
    """Resolve a directory we must never index, even when it does not exist yet."""
    try:
        return Path(path).expanduser().resolve(strict=False)
    except OSError:
        return None


def _is_within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _is_within_any(path: Path, roots: tuple[Path, ...]) -> bool:
    return any(_is_within(path, root) for root in roots)


def _local_file_entry(
    rel: str, abspath: Path, max_file_bytes: int
) -> tuple[str, str, int] | None:
    """Apply the indexer's file filters to one already-confined candidate."""
    if not is_supported(rel) or is_secret_path(rel):
        return None
    try:
        if not abspath.is_file():
            return None
        size = abspath.stat().st_size
    except OSError:
        return None
    if size == 0 or size > max_file_bytes:
        return None
    if not rel.lower().endswith(".pdf"):
        try:
            with abspath.open("rb") as handle:
                head = handle.read(2048)
        except OSError:
            return None
        if looks_binary(head):
            return None
    return rel, str(abspath), size


def _walk_local_tree(
    root: Path, max_file_bytes: int, excluded: tuple[Path, ...]
):
    """Walk ``root`` without ever descending through an escaping link/junction.

    Every directory is resolved strictly and checked *before* it is opened, so
    an outside tree is never traversed. Files are resolved too; only entries
    whose real path stays inside ``root`` (and outside Nova-owned dirs) are
    yielded. In-root links still work; ``visited`` prevents link cycles from
    duplicating or looping the walk.
    """
    visited: set[Path] = set()
    stack: list[tuple[Path, str]] = [(root, "")]
    while stack:
        directory, prefix = stack.pop()
        real_dir = _resolve_strict(directory)
        if real_dir is None or not real_dir.is_dir():
            continue
        if not _is_within(real_dir, root) or _is_within_any(real_dir, excluded):
            continue
        if real_dir in visited:
            continue
        visited.add(real_dir)
        try:
            with os.scandir(directory) as scan:
                entries = []
                for entry in scan:
                    try:
                        is_dir = entry.is_dir(follow_symlinks=False)
                    except OSError:
                        continue
                    entries.append((entry.name, entry.path, is_dir))
        except OSError:
            continue
        entries.sort(key=lambda item: item[0].lower())
        subdirs: list[tuple[Path, str]] = []
        for name, entry_path, is_dir in entries:
            rel = f"{prefix}/{name}" if prefix else name
            if is_dir:
                if name not in SKIP_DIRS:
                    subdirs.append((Path(entry_path), rel))
                continue
            # Symlinks-to-directories report is_dir(False) without following,
            # so resolve before deciding whether this is a dir or a file.
            abspath = _resolve_strict(entry_path)
            if abspath is None:
                continue
            if not _is_within(abspath, root) or _is_within_any(abspath, excluded):
                continue
            if abspath.is_dir():
                if name not in SKIP_DIRS:
                    subdirs.append((Path(entry_path), rel))
                continue
            entry_data = _local_file_entry(rel, abspath, max_file_bytes)
            if entry_data is not None:
                yield entry_data
        # Reverse so the first (alphabetical) subdirectory is walked first.
        stack.extend(reversed(subdirs))


def _iter_local_project_files(
    root: str | Path,
    max_file_bytes: int,
    excluded_roots: tuple[Path, ...] = (),
):
    root_path = _resolve_strict(root)
    if root_path is None or not root_path.is_dir():
        return
    excluded = tuple(
        resolved
        for resolved in (_resolve_excluded(path) for path in excluded_roots)
        if resolved is not None
    )
    if _is_within_any(root_path, excluded):
        return
    listed = _git_listed_files(root_path)
    if listed is None:
        yield from _walk_local_tree(root_path, max_file_bytes, excluded)
        return
    for raw in listed:
        rel = raw.replace("\\", "/")
        if not is_supported(rel) or is_secret_path(rel):
            continue
        abspath = _resolve_strict(root_path / rel)
        if abspath is None:
            continue
        if not _is_within(abspath, root_path) or _is_within_any(abspath, excluded):
            continue
        entry = _local_file_entry(rel, abspath, max_file_bytes)
        if entry is not None:
            yield entry


def iter_local_project_files(root: str, max_file_bytes: int):
    """Yield project files under ``root``, honoring .gitignore.

    Enumeration is confined to the registered root: symlinks, junctions and
    other reparse points that resolve outside it are pruned before traversal.
    """
    yield from _iter_local_project_files(root, max_file_bytes)


def iter_local_project_files_excluding(
    root: str, max_file_bytes: int, excluded_roots: tuple[Path, ...] = ()
):
    """Like ``iter_local_project_files`` but also prunes Nova-owned dirs.

    Used by the indexer as defense in depth so a project that (incorrectly)
    contains the Nova data directory can never index Nova's own secrets.
    """
    yield from _iter_local_project_files(root, max_file_bytes, excluded_roots)

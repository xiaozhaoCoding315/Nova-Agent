"""Shared filesystem helpers for the grep/glob tools."""
import os
import re
from pathlib import Path, PurePosixPath
from typing import Iterator

from app.core.indexing.languages import SKIP_DIRS
from app.core.security.paths import (
    UnsafePathError, normalize_relpath, resolve_repo_path,
)
from app.core.tools.base import ToolBusinessError

MAX_FILE_BYTES = 1_000_000
MAX_SCANNED_FILES = 5000


def glob_to_regex(pattern: str) -> re.Pattern:
    """Translate a glob pattern to a regex with standard segment semantics."""
    out = ["^"]
    i = 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == "*":
            if i + 1 < len(pattern) and pattern[i + 1] == "*":
                if i + 2 < len(pattern) and pattern[i + 2] == "/":
                    out.append("(?:.*/)?")
                    i += 3
                else:
                    out.append(".*")
                    i += 2
                continue
            out.append("[^/]*")
            i += 1
            continue
        if ch == "?":
            out.append("[^/]")
            i += 1
            continue
        if ch == "[":
            end = pattern.find("]", i + 1)
            if end == -1:
                out.append(re.escape(ch))
                i += 1
                continue
            char_class = pattern[i:end + 1]
            if char_class.startswith("[!"):
                char_class = "[^" + char_class[2:]
            out.append(char_class)
            i = end + 1
            continue
        out.append(re.escape(ch))
        i += 1
    out.append("$")
    try:
        return re.compile("".join(out))
    except re.error as exc:
        raise ToolBusinessError(f"glob 模式不合法：{exc}")


def matches_patterns(rel: str, patterns: list[re.Pattern]) -> bool:
    if not patterns:
        return True
    name = PurePosixPath(rel).name
    return any(pattern.match(rel) or pattern.match(name) for pattern in patterns)


def iter_files(root: Path, start: Path) -> Iterator[Path]:
    if start.is_file():
        yield start
        return
    for dirpath, dirnames, filenames in os.walk(start, followlinks=False):
        dirnames[:] = sorted(name for name in dirnames if name not in SKIP_DIRS)
        for name in filenames:
            yield Path(dirpath) / name


def is_inside(root: Path, path: Path) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        return False
    return resolved == root or root in resolved.parents


async def resolve_scope(args: dict, ctx) -> tuple[Path, Path, str]:
    """Resolve (repo_root, scan_start, repo_name) with path safety."""
    from app.core.indexing.pipeline import get_repo
    from app.core.tools.base import ToolBusinessError

    repo_id = args.get("repo_id") or (ctx.repo_ids[0] if ctx.repo_ids else None)
    if not repo_id:
        raise ToolBusinessError("需要指定 repo_id，或先在会话中关联仓库")
    repo = await get_repo(str(repo_id), ctx.user["id"])
    if not repo:
        raise ToolBusinessError("仓库不存在或无权访问")
    root = Path(repo["root_path"]).resolve()
    if not root.is_dir():
        raise ToolBusinessError("仓库文件已不存在，请重新导入")

    raw_prefix = str(args.get("path") or "").strip().replace("\\", "/")
    if raw_prefix in ("", ".", "./"):
        return root, root, repo["name"]
    try:
        rel = normalize_relpath(raw_prefix)
        start = resolve_repo_path(str(root), rel)
    except UnsafePathError as exc:
        raise ToolBusinessError(str(exc))
    if not start.exists():
        raise ToolBusinessError(f"路径不存在：{rel}")
    return root, start, repo["name"]

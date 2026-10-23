"""Repo acquisition (zip upload / public git clone) and safe file traversal."""
import asyncio
import os
import shutil
import zipfile
from pathlib import Path

import structlog

from app.core.indexing.languages import SKIP_DIRS, is_supported, looks_binary

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
    """Shallow-clone a public http(s) repo, then drop the .git directory."""
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
    shutil.rmtree(Path(dest) / ".git", ignore_errors=True)


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
            if not is_supported(rel):
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
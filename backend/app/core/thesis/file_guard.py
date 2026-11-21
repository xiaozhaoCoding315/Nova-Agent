"""Per-turn integrity guard for thesis artifacts.

The policy layer denies tool arguments and commands that point into the thesis
container, but that is a lexical check: an obfuscated script can still compute
the path at runtime.  Before the first mutating tool call of a thesis turn we
snapshot every known DOCX/PDF artifact, and after the call we restore anything
whose size or mtime changed.  The guard is deliberately narrow: it protects
known artifacts, it does not sandbox execution, and it never deletes files the
turn created.
"""
from __future__ import annotations

import asyncio
import hashlib
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import structlog

logger = structlog.get_logger()


@dataclass
class _Snapshot:
    path: Path
    copy: Path
    size: int
    mtime_ns: int


def _digest(path: Path) -> str:
    sha = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(1024 * 1024):
            sha.update(chunk)
    return sha.hexdigest()


class ThesisFileGuard:
    """Snapshot once, then verify/restore after every mutating tool call."""

    def __init__(self, paths: Iterable[str | Path]):
        self._paths = [Path(p) for p in paths if p]
        self._snapshots: list[_Snapshot] = []
        self._dir: Path | None = None

    @property
    def active(self) -> bool:
        return bool(self._snapshots)

    async def snapshot(self) -> None:
        if self._dir is not None:
            return
        self._dir = Path(tempfile.mkdtemp(prefix="nova-thesis-guard-"))
        for index, path in enumerate(self._paths):
            if not path.is_file():
                continue
            copy = self._dir / f"{index}.bin"
            try:
                await asyncio.to_thread(shutil.copy2, path, copy)
                stat = path.stat()
            except OSError as exc:
                logger.warning(
                    "thesis_guard_snapshot_failed", path=str(path), error=str(exc)
                )
                continue
            self._snapshots.append(_Snapshot(
                path=path, copy=copy, size=stat.st_size, mtime_ns=stat.st_mtime_ns,
            ))

    async def verify_and_restore(self) -> list[str]:
        """Restore artifacts modified or removed since the snapshot.

        Returns display paths (relative to the artifact root when possible) so
        the caller can surface a notice without leaking host paths.
        """
        restored: list[str] = []
        for item in self._snapshots:
            try:
                stat = item.path.stat() if item.path.exists() else None
            except OSError:
                stat = None
            changed = (
                stat is None
                or stat.st_size != item.size
                or stat.st_mtime_ns != item.mtime_ns
            )
            if not changed:
                continue
            if stat is not None:
                try:
                    same = await asyncio.to_thread(
                        lambda p=item.path, c=item.copy: _digest(p) == _digest(c)
                    )
                except OSError:
                    same = False
                if same:
                    # Touch-only change (metadata refresh); record the new stat.
                    item.size = stat.st_size
                    item.mtime_ns = stat.st_mtime_ns
                    continue
            try:
                await asyncio.to_thread(shutil.copy2, item.copy, item.path)
                stat = item.path.stat()
                item.size = stat.st_size
                item.mtime_ns = stat.st_mtime_ns
                restored.append(item.path.name)
            except OSError as exc:
                logger.warning(
                    "thesis_guard_restore_failed", path=str(item.path), error=str(exc)
                )
        if restored:
            logger.warning("thesis_guard_restored", files=restored)
        return restored

    async def cleanup(self) -> None:
        directory, self._dir = self._dir, None
        if directory is not None:
            await asyncio.to_thread(shutil.rmtree, directory, True)

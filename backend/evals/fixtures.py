"""Synthetic repositories used by eval tasks."""
from __future__ import annotations

import base64
import hashlib
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

EVAL_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8"
    "z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)

CALC_PY = """def add(a, b):
    return a - b


def multiply(a, b):
    return a * b
"""

TEST_CALC_PY = """from calc import add, multiply


def test_add():
    assert add(2, 3) == 5


def test_multiply():
    assert multiply(2, 3) == 6
"""

README_MD = "# Eval Fixture\n\nSynthetic repository for Nova Agent evals.\n"

_FIXTURES: dict[str, dict[str, str]] = {
    "python_small": {
        "calc.py": CALC_PY,
        "test_calc.py": TEST_CALC_PY,
        "README.md": README_MD,
    },
    "empty": {"README.md": README_MD},
}

_IGNORED_PARTS = {".git", "__pycache__", ".pytest_cache", ".ruff_cache"}
_IGNORED_SUFFIXES = {".pyc"}


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            "git",
            "-c", "user.name=Nova Eval",
            "-c", "user.email=eval@nova.local",
            "-c", "commit.gpgsign=false",
            *args,
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _rmtree(root: Path) -> None:
    """Remove ``root`` even when git left read-only entries behind.

    Git marks loose objects read-only and Windows refuses to delete read-only
    files, so add the owner write bit to every entry first.  The existing mode
    bits are preserved: replacing them with a bare ``0o200`` would strip the
    read/execute bits POSIX needs to descend into directories.
    """
    for path in root.rglob("*"):
        try:
            path.chmod(path.stat().st_mode | stat.S_IWRITE)
        except OSError:
            pass
    shutil.rmtree(root, ignore_errors=True)


def _visible_files(root: Path) -> dict[str, Path]:
    files: dict[str, Path] = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if any(part in _IGNORED_PARTS for part in rel.parts):
            continue
        if path.suffix in _IGNORED_SUFFIXES:
            continue
        files[rel.as_posix()] = path
    return files


@dataclass
class FixtureRepo:
    root: Path
    repo_id: str = "eval-repo"
    initial: dict[str, str] = field(default_factory=dict)

    def read(self, rel: str) -> str:
        return (self.root / rel).read_text(encoding="utf-8")

    def exists(self, rel: str) -> bool:
        return (self.root / rel).is_file()

    def digest(self, rel: str) -> str:
        return _sha256(self.read(rel))

    def is_unchanged(self, rel: str) -> bool:
        return self.exists(rel) and self.initial.get(rel) == self.digest(rel)

    def changed_files(self) -> list[str]:
        current = {
            rel: _sha256(path.read_text(encoding="utf-8", errors="replace"))
            for rel, path in _visible_files(self.root).items()
        }
        changed = [
            rel for rel, digest in current.items()
            if self.initial.get(rel) != digest
        ]
        changed.extend(rel for rel in self.initial if rel not in current)
        return sorted(changed)

    def run_pytest(
        self, *targets: str, timeout: float = 60.0
    ) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "pytest", "-q", *targets],
            cwd=self.root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )

    def cleanup(self) -> None:
        _rmtree(self.root)


def create_fixture(name: str) -> FixtureRepo:
    try:
        files = _FIXTURES[name]
    except KeyError as exc:
        raise ValueError(f"未知 fixture：{name}") from exc

    root = Path(tempfile.mkdtemp(prefix="nova-eval-"))
    for rel, content in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    try:
        _git(root, "init", "-q")
        _git(root, "add", "-A")
        _git(root, "commit", "-q", "-m", "fixture")
    except FileNotFoundError as exc:
        _rmtree(root)
        raise RuntimeError("eval fixtures 需要本机安装 git") from exc
    except subprocess.CalledProcessError as exc:
        _rmtree(root)
        detail = (exc.stderr or "").strip()[-500:]
        raise RuntimeError(f"fixture git 初始化失败：{detail}") from exc

    initial = {
        rel: _sha256((root / rel).read_text(encoding="utf-8"))
        for rel in files
    }
    return FixtureRepo(root=root, initial=initial)

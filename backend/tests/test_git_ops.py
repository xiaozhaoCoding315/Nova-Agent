"""Git delivery tests (skipped when git is not installed)."""
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from app.core.git_ops.service import (
    commit,
    diff,
    export_zip,
    git_available,
    init_repo,
    rollback,
    status,
)

pytestmark = pytest.mark.skipif(not git_available(), reason="git not installed")


@pytest.mark.asyncio
async def test_git_init_commit_diff_rollback(tmp_path):
    (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
    info = await init_repo(tmp_path)
    assert info["initialized"] is True
    assert info["commits"]
    first = info["commits"][0]["hash"]

    (tmp_path / "app.py").write_text("x = 2\n", encoding="utf-8")
    dirty = await status(tmp_path)
    assert dirty["dirty"] is True and dirty["changed_files"] >= 1

    patch = await diff(tmp_path)
    assert "+x = 2" in patch

    info = await commit(tmp_path, "change x")
    assert info["dirty"] is False
    assert info["commits"][0]["message"] == "change x"

    await rollback(tmp_path, first)
    assert (tmp_path / "app.py").read_text(encoding="utf-8") == "x = 1\n"


@pytest.mark.asyncio
async def test_rollback_rejects_bad_hash(tmp_path):
    (tmp_path / "a.txt").write_text("hi", encoding="utf-8")
    await init_repo(tmp_path)
    with pytest.raises(ValueError):
        await rollback(tmp_path, "rm -rf /")


def test_export_zip_excludes_git(tmp_path):
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("x", encoding="utf-8")
    path = export_zip(tmp_path)
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
        assert "a.txt" in names
        assert all(not name.startswith(".git/") for name in names)
    finally:
        path.unlink(missing_ok=True)


def test_cli_help_smoke():
    cli = Path(__file__).resolve().parents[1] / "nova.py"
    result = subprocess.run(
        [sys.executable, str(cli), "--help"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0
    assert "Nova Agent headless CLI" in result.stdout
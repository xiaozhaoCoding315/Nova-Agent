"""grep/glob: filesystem search independent of the code index."""
import os

import pytest

from app.core.tools import build_registry
from app.core.tools.base import ToolContext

USER = {"id": 1, "role": "admin"}


@pytest.fixture
def repo(tmp_path, monkeypatch):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text(
        "def login(user):\n    return 1\n", encoding="utf-8"
    )
    (tmp_path / "src" / "notes.md").write_text("login docs\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "x.py").write_text("login\n", encoding="utf-8")
    (tmp_path / ".env").write_text("SECRET=login\n", encoding="utf-8")
    (tmp_path / "bin.dat").write_bytes(b"login\x00\x01")

    async def fake_get_repo(repo_id, user_id):
        return {"id": repo_id, "name": "demo", "root_path": str(tmp_path)}

    monkeypatch.setattr("app.core.indexing.pipeline.get_repo", fake_get_repo)
    return tmp_path


def ctx(mode="readonly"):
    return ToolContext(user=USER, repo_ids=["repo-1"], permission_mode=mode)


@pytest.mark.asyncio
async def test_grep_content_search_skips_ignored_and_secret_files(repo):
    result = await build_registry().execute("grep", {"pattern": "login"}, ctx())
    assert result["ok"] is True
    matches = result["output"]["matches"]
    paths = {item["path"] for item in matches}
    assert "src/app.py" in paths
    assert "src/notes.md" in paths
    assert all(not path.startswith("node_modules/") for path in paths)
    assert ".env" not in paths
    assert "bin.dat" not in paths


@pytest.mark.asyncio
async def test_grep_glob_filter_and_case_sensitivity(repo):
    result = await build_registry().execute(
        "grep", {"pattern": "login", "glob": "*.py"}, ctx()
    )
    assert {item["path"] for item in result["output"]["matches"]} == {"src/app.py"}

    insensitive = await build_registry().execute(
        "grep", {"pattern": "LOGIN"}, ctx()
    )
    assert insensitive["output"]["match_count"] >= 1

    sensitive = await build_registry().execute(
        "grep", {"pattern": "LOGIN", "case_sensitive": True}, ctx()
    )
    assert sensitive["output"]["match_count"] == 0


@pytest.mark.asyncio
async def test_grep_context_lines(repo):
    result = await build_registry().execute(
        "grep", {"pattern": "return 1", "context_lines": 1}, ctx()
    )
    match = result["output"]["matches"][0]
    assert match["line"] == 2
    assert match["before"] == ["def login(user):"]


@pytest.mark.asyncio
async def test_grep_output_modes(repo):
    files = await build_registry().execute(
        "grep", {"pattern": "login", "output_mode": "files_with_matches"}, ctx()
    )
    assert files["output"]["file_count"] >= 2
    assert all("count" in item for item in files["output"]["files"])

    counts = await build_registry().execute(
        "grep", {"pattern": "login", "output_mode": "count"}, ctx()
    )
    assert counts["output"]["total"] >= 2
    assert all("count" in item for item in counts["output"]["counts"])


@pytest.mark.asyncio
async def test_grep_result_limit_marks_truncated(repo):
    result = await build_registry().execute(
        "grep", {"pattern": "login", "max_results": 1}, ctx()
    )
    assert result["output"]["match_count"] == 1
    assert result["output"]["truncated"] is True


@pytest.mark.asyncio
async def test_grep_invalid_pattern_and_too_long(repo):
    invalid = await build_registry().execute("grep", {"pattern": "("}, ctx())
    assert invalid["ok"] is False and invalid["business"] is True
    assert "正则" in invalid["error"]

    too_long = await build_registry().execute(
        "grep", {"pattern": "a" * 501}, ctx()
    )
    assert too_long["ok"] is False and too_long["business"] is True
    assert "过长" in too_long["error"]


@pytest.mark.asyncio
async def test_grep_requires_repo_context():
    result = await build_registry().execute(
        "grep", {"pattern": "x"},
        ToolContext(user=USER, repo_ids=[], permission_mode="readonly"),
    )
    assert result["ok"] is False and result["business"] is True
    assert "repo_id" in result["error"]


@pytest.mark.asyncio
async def test_grep_skips_symlink_escape(repo):
    outside = repo.parent / "outside-secret.txt"
    outside.write_text("login\n", encoding="utf-8")
    link = repo / "link.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks are not available on this platform")

    result = await build_registry().execute("grep", {"pattern": "login"}, ctx())
    assert "link.txt" not in {item["path"] for item in result["output"]["matches"]}


@pytest.mark.asyncio
async def test_glob_matches_recursively_and_skips_ignored(repo):
    result = await build_registry().execute("glob", {"pattern": "**/*.py"}, ctx())
    assert result["ok"] is True
    paths = {item["path"] for item in result["output"]["files"]}
    assert "src/app.py" in paths
    assert "node_modules/x.py" not in paths


@pytest.mark.asyncio
async def test_glob_basename_pattern_matches_any_depth(repo):
    result = await build_registry().execute("glob", {"pattern": "*.py"}, ctx())
    paths = {item["path"] for item in result["output"]["files"]}
    assert "src/app.py" in paths


@pytest.mark.asyncio
async def test_glob_sorts_by_mtime_and_limits(repo):
    sorted_dir = repo / "sorted"
    sorted_dir.mkdir()
    older = sorted_dir / "older.py"
    newer = sorted_dir / "newer.py"
    older.write_text("x = 1\n", encoding="utf-8")
    newer.write_text("x = 2\n", encoding="utf-8")
    os.utime(older, (1_000_000, 1_000_000))
    os.utime(newer, (2_000_000, 2_000_000))

    result = await build_registry().execute(
        "glob", {"pattern": "sorted/*.py", "limit": 1}, ctx()
    )
    files = result["output"]["files"]
    assert len(files) == 1
    assert files[0]["path"] == "sorted/newer.py"
    assert result["output"]["truncated"] is True


@pytest.mark.asyncio
async def test_glob_skips_secret_files(repo):
    result = await build_registry().execute("glob", {"pattern": "**/*"}, ctx())
    paths = {item["path"] for item in result["output"]["files"]}
    assert ".env" not in paths


@pytest.mark.asyncio
async def test_glob_requires_repo_context():
    result = await build_registry().execute(
        "glob", {"pattern": "*.py"},
        ToolContext(user=USER, repo_ids=[], permission_mode="readonly"),
    )
    assert result["ok"] is False and result["business"] is True
    assert "repo_id" in result["error"]

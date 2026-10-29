"""edit_file tool: exact-match edits, approval reuse, business errors."""
import pytest

from app.core.tools import build_registry
from app.core.tools import edit_file as edit_file_mod
from app.core.tools.base import ToolContext

USER = {"id": 1, "role": "admin"}


@pytest.fixture
def repo(tmp_path, monkeypatch):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text(
        "def login(user):\n    return token\n", encoding="utf-8"
    )

    async def fake_get_repo(repo_id, user_id):
        return {"id": repo_id, "name": "demo", "root_path": str(tmp_path)}

    monkeypatch.setattr(edit_file_mod, "get_repo", fake_get_repo)
    return tmp_path


@pytest.fixture
def captured(monkeypatch):
    calls = {}

    async def fake_create_edit(**kwargs):
        calls.update(kwargs)
        return {
            "id": "edit-1",
            "staged": kwargs["mode"] == "ask",
            "status": "pending" if kwargs["mode"] == "ask" else "applied",
            "files": list(kwargs["files"]),
            "diff": "diff",
        }

    monkeypatch.setattr(edit_file_mod, "create_edit", fake_create_edit)
    return calls


def ctx(mode="ask"):
    return ToolContext(user=USER, repo_ids=["repo-1"], permission_mode=mode)


@pytest.mark.asyncio
async def test_replaces_unique_string_and_reuses_approval(repo, captured):
    result = await build_registry().execute("edit_file", {
        "path": "src/app.py",
        "edits": [{"old_string": "return token", "new_string": "return token, expires_at"}],
    }, ctx())

    assert result["ok"] is True
    assert result["output"]["edit_id"] == "edit-1"
    assert result["output"]["staged"] is True
    assert result["output"]["occurrences"] == 1
    assert captured["files"]["src/app.py"] == (
        "def login(user):\n    return token, expires_at\n"
    )
    assert captured["mode"] == "ask"


@pytest.mark.asyncio
async def test_missing_old_string_is_business_error(repo, captured):
    result = await build_registry().execute("edit_file", {
        "path": "src/app.py",
        "edits": [{"old_string": "return tokenz", "new_string": "x"}],
    }, ctx())

    assert result["ok"] is False and result["business"] is True
    assert "未找到" in result["error"]
    assert "return token" in result["error"]


@pytest.mark.asyncio
async def test_ambiguous_match_requires_replace_all(repo, captured):
    (repo / "src" / "app.py").write_text("x = 1\nx = 1\n", encoding="utf-8")
    result = await build_registry().execute("edit_file", {
        "path": "src/app.py",
        "edits": [{"old_string": "x = 1", "new_string": "x = 2"}],
    }, ctx())

    assert result["ok"] is False and result["business"] is True
    assert "匹配到 2 处" in result["error"]


@pytest.mark.asyncio
async def test_replace_all_replaces_every_occurrence(repo, captured):
    (repo / "src" / "app.py").write_text("x = 1\nx = 1\n", encoding="utf-8")
    result = await build_registry().execute("edit_file", {
        "path": "src/app.py",
        "edits": [{"old_string": "x = 1", "new_string": "x = 2", "replace_all": True}],
    }, ctx())

    assert result["ok"] is True
    assert result["output"]["occurrences"] == 2
    assert captured["files"]["src/app.py"].count("x = 2") == 2


@pytest.mark.asyncio
async def test_multiple_edits_apply_in_order(repo, captured):
    (repo / "src" / "app.py").write_text("a\nb\n", encoding="utf-8")
    result = await build_registry().execute("edit_file", {
        "path": "src/app.py",
        "edits": [
            {"old_string": "a", "new_string": "A"},
            {"old_string": "b", "new_string": "B"},
        ],
    }, ctx())

    assert result["ok"] is True
    assert captured["files"]["src/app.py"] == "A\nB\n"


@pytest.mark.asyncio
async def test_noop_edit_is_business_error(repo, captured):
    result = await build_registry().execute("edit_file", {
        "path": "src/app.py",
        "edits": [{"old_string": "return token", "new_string": "return token"}],
    }, ctx())

    assert result["ok"] is False and result["business"] is True
    assert "没有实际改动" in result["error"]


@pytest.mark.asyncio
async def test_readonly_mode_is_denied(repo, captured):
    result = await build_registry().execute("edit_file", {
        "path": "src/app.py",
        "edits": [{"old_string": "return token", "new_string": "x"}],
    }, ctx("readonly"))

    assert result["ok"] is False and result["business"] is True
    assert "只读" in result["error"]


@pytest.mark.asyncio
async def test_secret_path_is_denied(repo, captured):
    result = await build_registry().execute("edit_file", {
        "path": ".env",
        "edits": [{"old_string": "A", "new_string": "B"}],
    }, ctx())

    assert result["ok"] is False and result["business"] is True
    assert "密钥" in result["error"]


@pytest.mark.asyncio
async def test_oversized_result_is_rejected(repo, captured):
    (repo / "src" / "app.py").write_text("a" * 120_000, encoding="utf-8")
    result = await build_registry().execute("edit_file", {
        "path": "src/app.py",
        "edits": [{"old_string": "a", "new_string": "bb", "replace_all": True}],
    }, ctx())

    assert result["ok"] is False and result["business"] is True
    assert "120000" in result["error"]


@pytest.mark.asyncio
async def test_existing_tests_cannot_be_removed(repo, monkeypatch):
    (repo / "tests").mkdir()
    (repo / "tests" / "test_x.py").write_text(
        "def test_a():\n    pass\n\ndef helper():\n    pass\n", encoding="utf-8"
    )
    import app.core.editing.service as editing

    async def fake_execute(sql, params):
        return None

    async def fake_get_repo(repo_id, user_id):
        return {"id": repo_id, "name": "demo", "root_path": str(repo)}

    monkeypatch.setattr(editing, "execute", fake_execute)
    monkeypatch.setattr(editing, "get_repo", fake_get_repo)

    result = await build_registry().execute("edit_file", {
        "path": "tests/test_x.py",
        "edits": [{"old_string": "def test_a():\n    pass\n\n", "new_string": ""}],
    }, ctx())

    assert result["ok"] is False and result["business"] is True
    assert "删除了已有测试" in result["error"]

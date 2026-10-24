"""Editing pipeline: path safety, diffs, and permission-mode gating."""
from unittest.mock import AsyncMock

import pytest

from app.core.editing.service import build_diff, validate_changes
from app.core.tools.base import ToolContext, ToolDefinition, ToolRegistry


def test_validate_changes_rejects_unsafe_paths():
    changes = validate_changes({
        "../escape.py": "x",
        "/abs.py": "x",
        "C:/win.py": "x",
        ".env": "SECRET=1",
        "certs/server.pem": "key",
        "app/ok.py": "print(1)",
        "empty.py": "   ",
    })
    assert changes == {"app/ok.py": "print(1)"}


def test_validate_changes_caps_files():
    many = {f"f{i}.py": "x" for i in range(50)}
    assert len(validate_changes(many)) <= 20


def test_build_diff_new_and_modified():
    diff = build_diff(
        {"a.py": "x = 1\n", "new.py": None},
        {"a.py": "x = 2\n", "new.py": "y = 1\n"},
    )
    assert "-x = 1" in diff and "+x = 2" in diff
    assert "/dev/null" in diff and "+y = 1" in diff


def _registry_with(category: str) -> tuple[ToolRegistry, AsyncMock]:
    func = AsyncMock(return_value={"ok": True})
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="t", description="", parameters={}, func=func, category=category,
    ))
    return registry, func


@pytest.mark.asyncio
async def test_readonly_blocks_write_and_execute():
    for category in ("write", "execute"):
        registry, func = _registry_with(category)
        ctx = ToolContext(user={"id": 1}, permission_mode="readonly")
        result = await registry.execute("t", {}, ctx)
        assert result["ok"] is False and result["business"] is True
        assert "只读" in result["error"]
        assert func.await_count == 0


@pytest.mark.asyncio
async def test_ask_still_allows_execute_and_read():
    for category in ("execute", "read", "network"):
        registry, func = _registry_with(category)
        ctx = ToolContext(user={"id": 1}, permission_mode="ask")
        result = await registry.execute("t", {}, ctx)
        assert result["ok"] is True
        assert func.await_count == 1

@pytest.mark.asyncio
async def test_full_mode_writes_immediately(tmp_path, monkeypatch):
    from app.core.editing import service as editing

    async def fake_get_repo(repo_id, user_id):
        return {"root_path": str(tmp_path), "name": "r"}

    async def fake_execute(sql, params):
        return None

    monkeypatch.setattr(editing, "get_repo", fake_get_repo)
    monkeypatch.setattr(editing, "execute", fake_execute)

    edit = await editing.create_edit(
        1, None, "repo-1", {"app/x.py": "print(1)"}, mode="full"
    )
    assert edit["staged"] is False and edit["status"] == "applied"
    assert (tmp_path / "app" / "x.py").read_text(encoding="utf-8") == "print(1)"


@pytest.mark.asyncio
async def test_full_mode_allows_write_category():
    for category in ("write", "execute"):
        registry, func = _registry_with(category)
        ctx = ToolContext(user={"id": 1}, permission_mode="full")
        result = await registry.execute("t", {}, ctx)
        assert result["ok"] is True
        assert func.await_count == 1

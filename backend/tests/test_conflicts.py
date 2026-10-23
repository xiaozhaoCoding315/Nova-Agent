"""Conflict detection rejects stale proposals instead of overwriting."""
from unittest.mock import AsyncMock

import pytest

from app.core.conflicts import ConflictError
from app.core.editing import service as editing_mod


@pytest.mark.asyncio
async def test_apply_edit_rejects_changed_file(monkeypatch, tmp_path):
    target = tmp_path / "app.py"
    target.write_text("user changed this\n", encoding="utf-8")

    monkeypatch.setattr(editing_mod, "get_repo", AsyncMock(return_value={"root_path": str(tmp_path)}))
    monkeypatch.setattr(
        editing_mod, "query",
        AsyncMock(return_value=[(
            "e1", "r1", "pending",
            {"app.py": "agent version\n"},
            {"app.py": "original\n"},
            None,
        )]),
    )
    monkeypatch.setattr(editing_mod, "execute", AsyncMock())

    with pytest.raises(ConflictError, match="已被修改"):
        await editing_mod.apply_edit("e1", 1)


@pytest.mark.asyncio
async def test_apply_edit_writes_when_base_matches(monkeypatch, tmp_path):
    target = tmp_path / "app.py"
    target.write_text("original\n", encoding="utf-8")

    monkeypatch.setattr(editing_mod, "get_repo", AsyncMock(return_value={"root_path": str(tmp_path)}))
    monkeypatch.setattr(
        editing_mod, "query",
        AsyncMock(return_value=[(
            "e1", "r1", "pending",
            {"app.py": "agent version\n"},
            {"app.py": "original\n"},
            None,
        )]),
    )
    monkeypatch.setattr(editing_mod, "execute", AsyncMock())
    monkeypatch.setattr("app.core.git_ops.service.auto_commit", AsyncMock(return_value=None))

    result = await editing_mod.apply_edit("e1", 1)
    assert result["applied"] == ["app.py"]
    assert target.read_text(encoding="utf-8") == "agent version\n"

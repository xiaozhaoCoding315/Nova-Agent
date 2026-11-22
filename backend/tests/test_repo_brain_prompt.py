"""Project brain prompt block: deterministic, bounded and redacted."""
from unittest.mock import AsyncMock

import pytest

from app.core.memory import brain as brain_mod

BRAIN = {
    "totals": {"files": 120, "lines": 4560},
    "languages": {"Python": 90, "TypeScript": 20, "CSS": 10, "Other": 5},
    "entry_points": ["app/main.py", "src/main.ts"],
    "hot_files": [
        {"path": "app/core/agent/loop.py", "inbound": 12, "outbound": 8},
        {"path": "app/db/init_db.py", "inbound": 6, "outbound": 2},
    ],
    "reading_order": ["app/main.py", "app/core/agent/loop.py", "app/db/init_db.py"],
}


def test_format_repo_brain_keeps_high_signal_fields():
    block = brain_mod.format_repo_brain("Nova Agent", BRAIN)

    assert "### Nova Agent" in block
    assert "120 文件 / 4560 行" in block
    assert "Python 90" in block
    assert "TypeScript 20" in block
    assert "Other 5" not in block  # top 3 only
    assert "app/main.py" in block
    assert "loop.py（入 12/出 8）" in block
    assert "→" in block


def test_format_repo_brain_redacts_secrets():
    block = brain_mod.format_repo_brain("Repo", {
        "entry_points": ["sk-abcdefghijklmnopqrstuvwxyz.py"],
    })

    assert "sk-abcdefghijklmnopqrstuvwxyz" not in block


def test_format_repo_brain_empty():
    assert brain_mod.format_repo_brain("Repo", {}) == ""


@pytest.mark.asyncio
async def test_build_block_is_bounded_and_skips_missing(monkeypatch):
    rows = [("Nova Agent", BRAIN)]
    monkeypatch.setattr(brain_mod, "query", AsyncMock(return_value=rows))

    block = await brain_mod.build_repo_brain_block(
        7, ["r1", "r2"], max_chars=200,
    )

    assert "## 项目大脑" in block
    assert len(block) <= 200


@pytest.mark.asyncio
async def test_build_block_returns_empty_without_brain(monkeypatch):
    monkeypatch.setattr(brain_mod, "query", AsyncMock(return_value=[("Repo", {})]))

    assert await brain_mod.build_repo_brain_block(7, ["r1"]) == ""

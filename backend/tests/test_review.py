"""Read-only reviewer output sanitizing and prompt contents."""
from unittest.mock import AsyncMock

import pytest

from app.core.review import service as review_service


def test_clean_review_sanitizes_verdict_and_items():
    review = review_service.clean_review({
        "verdict": "definitely-not-valid",
        "summary": "x" * 2000,
        "blocking": ["删除了测试", {"file": "a.py", "line": "7", "issue": "未处理异常", "suggestion": "加 try"}],
        "non_blocking": [{"message": "命名可读性"}],
        "evidence": ["diff 行 12", 123],
    })
    assert review["verdict"] == "warn"
    assert review["blocking"][0]["issue"] == "删除了测试"
    assert review["blocking"][1]["line"] == 7
    assert review["non_blocking"][0]["issue"] == "命名可读性"
    assert review["evidence"] == ["diff 行 12", "123"]
    assert len(review["summary"]) == 1500


@pytest.mark.asyncio
async def test_review_diff_injects_rules_and_diff(monkeypatch, tmp_path):
    (tmp_path / "AGENTS.md").write_text("所有接口必须写测试", encoding="utf-8")
    monkeypatch.setattr(review_service, "ensure_token_budget", AsyncMock())
    captured: dict = {}

    async def fake_llm(prompt, **kwargs):
        captured["prompt"] = prompt
        captured["kwargs"] = kwargs
        return {
            "verdict": "block",
            "summary": "缺少测试",
            "blocking": [{"file": "app/api.py", "line": 3, "issue": "新增接口没有测试"}],
            "non_blocking": [],
            "evidence": ["diff 中没有 tests/ 变更"],
        }

    monkeypatch.setattr(review_service, "llm_json", fake_llm)
    review = await review_service.review_diff(
        user_id=1,
        repo={"name": "demo", "root_path": str(tmp_path), "rules": ""},
        diff="+def handler(): ...",
        files={"app/api.py": "def handler(): ..."},
        title="新增接口",
    )

    assert review["verdict"] == "block"
    assert "所有接口必须写测试" in captured["prompt"]
    assert "def handler" in captured["prompt"]
    assert captured["kwargs"]["source"] == "review"

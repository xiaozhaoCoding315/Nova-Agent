"""Turn extraction distinguishes cross-project preferences from project facts."""
from unittest.mock import AsyncMock

import pytest

from app.core.memory import facts as facts_mod
from app.core.memory import policy as policy_mod
from app.core.memory import scope as scope_mod


class FakeLLM:
    def __init__(self, payload: str):
        self.payload = payload

    async def astream_with_tools(self, messages, tools):
        yield {"type": "content", "content": self.payload}
        yield {"type": "usage", "usage": {"input_tokens": 3, "output_tokens": 2}}


def test_parse_extraction_items_accepts_objects_and_legacy_strings():
    items = facts_mod.parse_extraction_items(
        '[{"text": "偏好中文", "kind": "preference", "scope": "global"}, "项目使用 FastAPI"]'
    )

    assert items == [
        {"text": "偏好中文", "kind": "preference", "scope": "global"},
        {"text": "项目使用 FastAPI", "kind": "fact", "scope": "current"},
    ]


def test_parse_extraction_items_ignores_malformed_entries():
    assert facts_mod.parse_extraction_items("not json") == []
    assert facts_mod.parse_extraction_items('[{"kind": "preference"}, 3]') == []


def test_global_scope_requires_cross_project_preference():
    dev = scope_mod.Scope("dev", "")
    repo = scope_mod.Scope("repo", "r1")

    assert facts_mod.resolve_fact_scope(
        {"kind": "preference", "scope": "global"}, dev, "我习惯用简洁的中文回答",
    ) == scope_mod.Scope("global", "")
    assert facts_mod.resolve_fact_scope(
        {"kind": "project", "scope": "global"}, repo, "这个仓库使用 FastAPI",
    ) == repo
    assert facts_mod.resolve_fact_scope(
        {"kind": "preference", "scope": "global"}, dev, "这个项目要部署在 8080 端口",
    ) == dev


def test_preference_cue_detection_is_case_insensitive():
    assert facts_mod.has_preference_cue("以后都用 pnpm")
    assert facts_mod.has_preference_cue("I always prefer ruff")
    assert not facts_mod.has_preference_cue("今天先修这个 bug")


@pytest.mark.asyncio
async def test_extract_facts_from_turn_routes_preferences_and_project_facts(monkeypatch):
    payload = (
        '[{"text": "用户偏好简洁的中文回答", "kind": "preference", "scope": "global"},'
        ' {"text": "这个仓库使用 FastAPI", "kind": "project", "scope": "current"},'
        ' "部署目标是 8080 端口"]'
    )
    monkeypatch.setattr(
        "app.core.llm.factory.get_llm", AsyncMock(return_value=FakeLLM(payload))
    )

    async def fake_harness(fn, **_kwargs):
        return await fn()

    monkeypatch.setattr(
        "app.core.harness.runtime.execute_with_harness", fake_harness
    )
    monkeypatch.setattr("app.core.llm.usage.record_usage", AsyncMock())
    monkeypatch.setattr("app.core.security.limits.ensure_token_budget", AsyncMock())
    monkeypatch.setattr(
        policy_mod, "get_policy",
        AsyncMock(return_value=policy_mod.DEFAULT_POLICY),
    )
    add_fact = AsyncMock(return_value=True)
    monkeypatch.setattr(facts_mod, "add_fact", add_fact)

    added = await facts_mod.extract_facts_from_turn(
        7, "以后回答简洁一点，这个仓库使用 FastAPI，部署到 8080",
        "好的", scope_type="repo", scope_id="r1",
    )

    assert added == 3
    calls = add_fact.await_args_list
    assert calls[0].args[1] == "用户偏好简洁的中文回答"
    assert calls[0].kwargs["scope_type"] == "global"
    assert calls[0].kwargs["category"] == "preference"
    assert calls[1].kwargs["scope_type"] == "repo"
    assert calls[1].kwargs["scope_id"] == "r1"
    assert calls[2].kwargs["scope_type"] == "repo"


@pytest.mark.asyncio
async def test_extract_high_risk_fact_waits_for_review(monkeypatch):
    payload = (
        '[{"text": "生产数据库密码放在 .env", "kind": "fact", "scope": "current"}]'
    )
    monkeypatch.setattr(
        "app.core.llm.factory.get_llm", AsyncMock(return_value=FakeLLM(payload))
    )

    async def fake_harness(fn, **_kwargs):
        return await fn()

    monkeypatch.setattr(
        "app.core.harness.runtime.execute_with_harness", fake_harness
    )
    monkeypatch.setattr("app.core.llm.usage.record_usage", AsyncMock())
    monkeypatch.setattr("app.core.security.limits.ensure_token_budget", AsyncMock())
    monkeypatch.setattr(
        policy_mod, "get_policy",
        AsyncMock(return_value=policy_mod.DEFAULT_POLICY),
    )
    add_fact = AsyncMock(return_value=True)
    monkeypatch.setattr(facts_mod, "add_fact", add_fact)

    await facts_mod.extract_facts_from_turn(
        7, "生产库密码在 .env 里，记住它", "好的", scope_type="dev",
    )

    assert add_fact.await_args.kwargs["status"] == facts_mod.STATUS_PENDING
    assert "密钥凭据" in add_fact.await_args.kwargs["risk_reason"]


@pytest.mark.asyncio
async def test_extract_facts_resolves_replaces_hint(monkeypatch):
    payload = (
        '[{"text": "偏好 ruff", "kind": "correction", "scope": "current", '
        '"replaces": "偏好 flake8"}]'
    )
    monkeypatch.setattr(
        "app.core.llm.factory.get_llm", AsyncMock(return_value=FakeLLM(payload))
    )

    async def fake_harness(fn, **_kwargs):
        return await fn()

    monkeypatch.setattr(
        "app.core.harness.runtime.execute_with_harness", fake_harness
    )
    monkeypatch.setattr("app.core.llm.usage.record_usage", AsyncMock())
    monkeypatch.setattr("app.core.security.limits.ensure_token_budget", AsyncMock())
    monkeypatch.setattr(
        policy_mod, "get_policy",
        AsyncMock(return_value=policy_mod.DEFAULT_POLICY),
    )
    monkeypatch.setattr(
        facts_mod, "_find_fact_by_hint", AsyncMock(return_value=12)
    )
    add_fact = AsyncMock(return_value=True)
    monkeypatch.setattr(facts_mod, "add_fact", add_fact)

    await facts_mod.extract_facts_from_turn(
        7, "以后不用 flake8 了，改用 ruff", "好的", scope_type="dev",
    )

    assert add_fact.await_args.kwargs["supersedes_id"] == 12
    assert add_fact.await_args.kwargs["category"] == "correction"

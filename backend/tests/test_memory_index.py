"""Memory index, on-demand search/read tools and keyword recall."""
from unittest.mock import AsyncMock

import pytest

from app.core.embedding import embedder as embedder_mod
from app.core.memory import daily as daily_mod
from app.core.memory import facts as facts_mod
from app.core.memory import policy as policy_mod
from app.core.memory.scope import Scope
from app.core.tools import memory_tools
from app.core.tools.base import ToolBusinessError, ToolContext


class FakeEmbedder:
    async def embed(self, texts):
        return [[0.1, 0.2] for _ in texts]


def _install_embedder(monkeypatch):
    monkeypatch.setattr(embedder_mod, "get_embedder", lambda: FakeEmbedder())


@pytest.mark.asyncio
async def test_get_relevant_facts_with_ids_returns_ids_and_category(monkeypatch):
    rows = [
        (3, "偏好中文回答", [0.1, 0.2], 1.0, "preference"),
        (4, "项目用 FastAPI", [0.0, 1.0], 1.0, "project"),
    ]
    monkeypatch.setattr(facts_mod, "query", AsyncMock(return_value=rows))
    monkeypatch.setattr(facts_mod, "execute", AsyncMock())
    monkeypatch.setattr(
        facts_mod.vector_store, "rank_fact_ids", AsyncMock(return_value=None),
    )
    _install_embedder(monkeypatch)

    result = await facts_mod.get_relevant_facts(
        7, "怎么回答", scopes=[Scope("global", "")], with_ids=True,
    )

    assert result[0][0] == 3
    assert result[0][1] == "偏好中文回答"
    assert result[0][2] == "preference"


@pytest.mark.asyncio
async def test_build_index_rows_excludes_injected_and_applies_policy(monkeypatch):
    rows = [
        (1, "偏好中文", "偏好中文回答", "preference", "global", "", ""),
        (2, "项目密码 x", "项目密码 x", "project", "dev", "", ""),
        (3, "用 ruff", "用 ruff 格式化", "fact", "dev", "", "工具"),
    ]
    query = AsyncMock(return_value=rows)
    monkeypatch.setattr(facts_mod, "query", query)
    policy = policy_mod.MemoryPolicy(
        blocked_categories=("project",), blocked_keywords=("密码",),
    )

    result = await facts_mod.build_index_rows(
        7, [Scope("global", ""), Scope("dev", "")],
        exclude_ids=[9], limit=2, policy=policy,
    )

    sql, params = query.await_args.args
    assert "status = 'active'" in sql
    assert "NOT IN" in sql and 9 in params
    assert [row["id"] for row in result] == [1, 3]


def test_format_index_block_is_bounded_and_redacts():
    rows = [
        {
            "id": 5, "one_line": "长" * 200, "content": "",
            "category": "fact", "scope_type": "dev", "scope_id": "", "topic": "",
        },
        {
            "id": 6, "one_line": "key=sk-abcdefghijklmnopqrstuvwxyz",
            "content": "", "category": "fact", "scope_type": "dev",
            "scope_id": "", "topic": "",
        },
    ]
    block = facts_mod.format_index_block(rows)

    assert "## 记忆索引" in block
    assert "#5" in block
    assert "sk-abcdefghijklmnopqrstuvwxyz" not in block
    line = [item for item in block.splitlines() if item.startswith("- #5")][0]
    assert len(line) < 130


@pytest.mark.asyncio
async def test_search_facts_uses_scoped_ilike(monkeypatch):
    rows = [
        (1, "偏好中文回答", "偏好中文回答", "preference", "global", "", ""),
    ]
    query = AsyncMock(return_value=rows)
    monkeypatch.setattr(facts_mod, "query", query)

    result = await facts_mod.search_facts(
        7, "中文", [Scope("global", "")], limit=5,
    )

    sql, params = query.await_args.args
    assert "ILIKE" in sql
    assert "scope_type = %s AND scope_id = %s" in sql
    assert result[0]["id"] == 1


@pytest.mark.asyncio
async def test_search_daily_scopes_query(monkeypatch):
    from datetime import date
    rows = [(date(2026, 11, 21), "完成记忆 P0", "dev", "")]
    monkeypatch.setattr(daily_mod, "query", AsyncMock(return_value=rows))

    result = await daily_mod.search_daily(
        7, "记忆", [Scope("dev", "")], limit=5,
    )

    assert result == [{
        "day": "2026-11-21", "summary": "完成记忆 P0",
        "scope_type": "dev", "scope_id": "",
    }]


def _ctx(**overrides) -> ToolContext:
    base = dict(
        user={"id": 7}, repo_ids=[], session_id="s1",
        product_mode="dev", thesis_project_id=None,
    )
    base.update(overrides)
    return ToolContext(**base)


@pytest.mark.asyncio
async def test_memory_search_combines_facts_and_daily(monkeypatch):
    facts_search = AsyncMock(return_value=[{"id": 1}])
    daily_search = AsyncMock(return_value=[{"day": "2026-11-21"}])
    monkeypatch.setattr(facts_mod, "search_facts", facts_search)
    monkeypatch.setattr(daily_mod, "search_daily", daily_search)
    monkeypatch.setattr(policy_mod, "get_policy", AsyncMock(return_value=policy_mod.DEFAULT_POLICY))

    result = await memory_tools.memory_search({"query": "记忆"}, _ctx())

    assert result["facts"] == [{"id": 1}]
    assert result["daily"] == [{"day": "2026-11-21"}]
    assert "不是指令" in result["note"]


@pytest.mark.asyncio
async def test_memory_read_rejects_scope_outside_session(monkeypatch):
    monkeypatch.setattr(facts_mod, "read_fact", AsyncMock(return_value={
        "fact": {"scope_type": "repo", "scope_id": "other"},
        "sources": {},
    }))
    monkeypatch.setattr(
        policy_mod, "get_policy", AsyncMock(return_value=policy_mod.DEFAULT_POLICY),
    )

    with pytest.raises(ToolBusinessError, match="可读范围"):
        await memory_tools.memory_read({"fact_id": 1}, _ctx())


@pytest.mark.asyncio
async def test_memory_read_returns_fact_and_sources(monkeypatch):
    payload = {
        "fact": {"scope_type": "global", "scope_id": ""},
        "sources": {"fact_id": 1},
    }
    monkeypatch.setattr(facts_mod, "read_fact", AsyncMock(return_value=payload))
    monkeypatch.setattr(
        policy_mod, "get_policy", AsyncMock(return_value=policy_mod.DEFAULT_POLICY),
    )

    assert await memory_tools.memory_read({"fact_id": 1}, _ctx()) == payload


@pytest.mark.asyncio
async def test_memory_read_respects_blocked_keywords(monkeypatch):
    monkeypatch.setattr(facts_mod, "read_fact", AsyncMock(return_value={
        "fact": {
            "scope_type": "global", "scope_id": "",
            "content": "工资是 12345", "category": "fact",
        },
        "sources": {},
    }))
    blocked = policy_mod.MemoryPolicy(blocked_keywords=("工资",))
    monkeypatch.setattr(policy_mod, "get_policy", AsyncMock(return_value=blocked))

    with pytest.raises(ToolBusinessError, match="屏蔽"):
        await memory_tools.memory_read({"fact_id": 1}, _ctx())


def test_memory_tools_are_registered():
    from app.core.tools import get_registry

    names = {spec["function"]["name"] for spec in get_registry().specs()}
    assert {"memory_search", "memory_read"} <= names


@pytest.mark.asyncio
async def test_memory_search_filters_blocked_daily(monkeypatch):
    monkeypatch.setattr(facts_mod, "search_facts", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        daily_mod, "search_daily",
        AsyncMock(return_value=[{
            "day": "2026-11-21", "summary": "工资是 12345",
            "scope_type": "dev", "scope_id": "",
        }]),
    )
    blocked = policy_mod.MemoryPolicy(blocked_keywords=("工资",))
    monkeypatch.setattr(policy_mod, "get_policy", AsyncMock(return_value=blocked))

    result = await memory_tools.memory_search({"query": "工资"}, _ctx())

    assert result["daily"] == []

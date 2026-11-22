"""Memory scopes keep dev, thesis, repo and global memories isolated."""
from datetime import date
from unittest.mock import AsyncMock

import pytest

from app.core.embedding import embedder as embedder_mod
from app.core.memory import daily as daily_mod
from app.core.memory import facts as facts_mod
from app.core.memory import scope as scope_mod


class FakeEmbedder:
    async def embed(self, texts):
        return [[0.1, 0.2] for _ in texts]


def test_extraction_scope_separates_dev_and_thesis():
    dev = scope_mod.extraction_scope({"product_mode": "dev"})
    thesis = scope_mod.extraction_scope(
        {"product_mode": "thesis", "thesis_project_id": "p1"}
    )
    orphan = scope_mod.extraction_scope({"product_mode": "thesis"})

    assert dev == scope_mod.Scope("dev", "")
    assert thesis == scope_mod.Scope("thesis", "p1")
    assert orphan is None


def test_extraction_scope_uses_repo_for_single_repo_dev_turn():
    scope = scope_mod.extraction_scope({"product_mode": "dev"}, ["r1"])
    multi = scope_mod.extraction_scope({"product_mode": "dev"}, ["r1", "r2"])

    assert scope == scope_mod.Scope("repo", "r1")
    assert multi == scope_mod.Scope("dev", "")


def test_readable_scopes_never_cross_product_surfaces():
    dev = scope_mod.readable_scopes(
        {"product_mode": "dev"}, ["r1", "r2"]
    )
    thesis = scope_mod.readable_scopes(
        {"product_mode": "thesis", "thesis_project_id": "p1"}, ["r1"]
    )

    assert dev == [
        scope_mod.Scope("global", ""),
        scope_mod.Scope("dev", ""),
        scope_mod.Scope("repo", "r1"),
        scope_mod.Scope("repo", "r2"),
    ]
    assert thesis == [
        scope_mod.Scope("global", ""),
        scope_mod.Scope("thesis", "p1"),
    ]


@pytest.mark.asyncio
async def test_add_fact_stores_scope_and_provenance(monkeypatch):
    query = AsyncMock(side_effect=[[], [(0,)]])
    execute = AsyncMock(side_effect=[[(1,)], []])
    monkeypatch.setattr(facts_mod, "query", query)
    monkeypatch.setattr(facts_mod, "execute", execute)
    monkeypatch.setattr(
        facts_mod, "_is_semantic_duplicate", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(embedder_mod, "get_embedder", lambda: FakeEmbedder())

    added = await facts_mod.add_fact(
        7, "论文方向是可解释推荐", scope_type="thesis", scope_id="p1",
        source_session_id="s1", source_message_id=99,
    )

    assert added is True
    dedup_sql, dedup_params = query.await_args_list[0].args
    assert "scope_type = %s" in dedup_sql
    assert dedup_params[:3] == (7, "thesis", "p1")
    insert_sql, insert_params = execute.await_args_list[0].args
    assert "scope_type" in insert_sql and "source_session_id" in insert_sql
    assert insert_params[6:10] == ("thesis", "p1", "s1", 99)


@pytest.mark.asyncio
async def test_semantic_duplicate_reinforces_existing_fact(monkeypatch):
    monkeypatch.setattr(facts_mod, "query", AsyncMock(side_effect=[[], [(0,)]]))
    execute = AsyncMock(side_effect=[[], []])
    monkeypatch.setattr(facts_mod, "execute", execute)
    monkeypatch.setattr(
        facts_mod, "_is_semantic_duplicate", AsyncMock(return_value=42)
    )
    monkeypatch.setattr(embedder_mod, "get_embedder", lambda: FakeEmbedder())

    added = await facts_mod.add_fact(7, "偏好 FastAPI")

    assert added is False
    reinforce_sql, reinforce_params = execute.await_args_list[0].args
    assert "WHERE id = %s AND user_id = %s" in reinforce_sql
    assert reinforce_params == (0.05, 42, 7)
    assert "INSERT INTO fact_days" in execute.await_args_list[1].args[0]


@pytest.mark.asyncio
async def test_full_scope_evicts_least_valuable_fact(monkeypatch):
    query = AsyncMock(side_effect=[[], [(facts_mod.MAX_FACTS_PER_SCOPE,)]])
    execute = AsyncMock(side_effect=[[(9,)], [(1,)], []])
    monkeypatch.setattr(facts_mod, "query", query)
    monkeypatch.setattr(facts_mod, "execute", execute)
    monkeypatch.setattr(
        facts_mod, "_is_semantic_duplicate", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(embedder_mod, "get_embedder", lambda: FakeEmbedder())

    assert await facts_mod.add_fact(7, "新的项目偏好") is True

    evict_sql, evict_params = execute.await_args_list[0].args
    assert "DELETE FROM facts WHERE id = (" in evict_sql
    assert "promoted_at IS NOT NULL" in evict_sql
    assert evict_params == (7, "global", "")
    assert "INSERT INTO facts" in execute.await_args_list[1].args[0]


@pytest.mark.asyncio
async def test_retrieval_filters_by_scope_without_importance_boost(monkeypatch):
    rows = [(1, "偏好 FastAPI", [1.0, 0.0], 1.0)]
    query = AsyncMock(return_value=rows)
    execute = AsyncMock()
    monkeypatch.setattr(facts_mod, "query", query)
    monkeypatch.setattr(facts_mod, "execute", execute)
    monkeypatch.setattr(embedder_mod, "get_embedder", lambda: FakeEmbedder())

    facts = await facts_mod.get_relevant_facts(
        1, "FastAPI", scopes=[scope_mod.Scope("dev", ""), scope_mod.Scope("repo", "r1")],
    )

    assert facts == ["偏好 FastAPI"]
    sql, params = query.await_args.args
    assert "scope_type = %s AND scope_id = %s" in sql
    assert params == (1, "dev", "", "repo", "r1", facts_mod.CANDIDATE_LIMIT)
    assert "LIMIT 80" not in sql
    update_sql = execute.await_args.args[0]
    assert "UPDATE facts SET last_used_at" in update_sql
    assert "importance = LEAST" not in update_sql


@pytest.mark.asyncio
async def test_cleanup_ttl_counts_from_last_use_and_decays_daily(monkeypatch):
    execute = AsyncMock(side_effect=[[], []])
    monkeypatch.setattr(facts_mod, "execute", execute)

    await facts_mod.run_cleanup()

    decay_sql = execute.await_args_list[0].args[0]
    ttl_sql = execute.await_args_list[1].args[0]
    assert "last_decayed_at" in decay_sql
    assert "CURRENT_DATE - last_decayed_at" in decay_sql
    assert "GREATEST(created_at, last_used_at)" in ttl_sql


@pytest.mark.asyncio
async def test_daily_rollup_is_scoped(monkeypatch):
    messages = [("user", f"消息 {i}") for i in range(10)]
    query = AsyncMock(side_effect=[[], messages])
    execute = AsyncMock()
    monkeypatch.setattr(daily_mod, "query", query)
    monkeypatch.setattr(daily_mod, "execute", execute)
    monkeypatch.setattr(
        daily_mod, "llm_json", AsyncMock(return_value={"summary": "论文进展"})
    )
    monkeypatch.setattr(daily_mod, "ensure_token_budget", AsyncMock())

    count = await daily_mod.rollup_day(
        1, date(2026, 10, 22), scope_type="thesis", scope_id="p1",
    )

    assert count == 10
    source_sql, source_params = query.await_args_list[1].args
    assert "s.thesis_project_id::text = %s" in source_sql
    assert source_params[0] == 1
    assert source_params[-1] == "p1"
    insert_sql, insert_params = execute.await_args.args
    assert "scope_type, scope_id" in insert_sql
    assert insert_params[4:6] == ("thesis", "p1")


@pytest.mark.asyncio
async def test_memory_api_filters_and_returns_scope(monkeypatch):
    from app.api.v1 import memory as memory_api

    fact_rows = [{
        "id": 1, "content": "论文方向", "importance": 1.2, "ttl_days": 90,
        "scope_type": "thesis", "scope_id": "p1",
        "source_session_id": "s1", "status": "active", "category": "project",
    }]
    daily_rows = [
        (date(2026, 10, 22), "论文进展", 10, None, None, "thesis", "p1"),
    ]
    list_facts = AsyncMock(return_value=fact_rows)
    query = AsyncMock(return_value=daily_rows)
    monkeypatch.setattr(memory_api.facts_mod, "list_facts", list_facts)
    monkeypatch.setattr(memory_api, "query", query)

    result = await memory_api.get_memory(
        scope_type="thesis", scope_id="p1", user={"id": 7},
    )

    list_facts.assert_awaited_once_with(
        7, scope_type="thesis", scope_id="p1", status=None,
        include_inactive=False,
    )
    assert result["facts"][0]["scope_type"] == "thesis"
    assert result["facts"][0]["source_session_id"] == "s1"
    daily_sql, daily_params = query.await_args.args
    assert "scope_type = %s" in daily_sql
    assert daily_params == (7, "thesis", "p1")
    assert result["daily"][0]["scope_id"] == "p1"


@pytest.mark.asyncio
async def test_memory_api_deletes_only_one_daily_scope(monkeypatch):
    from app.api.v1 import memory as memory_api

    execute = AsyncMock(return_value=[(date(2026, 10, 22),)])
    monkeypatch.setattr(memory_api, "execute", execute)

    await memory_api.delete_daily(
        "2026-10-22", scope_type="dev", scope_id="", user={"id": 7},
    )

    sql, params = execute.await_args.args
    assert "scope_type = %s AND scope_id = %s" in sql
    assert params == (7, date(2026, 10, 22), "dev", "")

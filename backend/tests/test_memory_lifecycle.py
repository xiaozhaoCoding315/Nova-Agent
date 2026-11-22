"""Fact lifecycle: versions, corrections, provenance and scoped edits."""
from unittest.mock import AsyncMock

import pytest

from app.core.embedding import embedder as embedder_mod
from app.core.memory import facts as facts_mod


class FakeEmbedder:
    async def embed(self, texts):
        return [[0.1, 0.2] for _ in texts]


def _install_embedder(monkeypatch):
    monkeypatch.setattr(embedder_mod, "get_embedder", lambda: FakeEmbedder())


@pytest.mark.asyncio
async def test_add_fact_persists_category_status_and_version(monkeypatch):
    query = AsyncMock(side_effect=[[], [(0,)]])
    execute = AsyncMock(side_effect=[[(42,)], []])
    monkeypatch.setattr(facts_mod, "query", query)
    monkeypatch.setattr(facts_mod, "execute", execute)
    monkeypatch.setattr(facts_mod, "_is_semantic_duplicate", AsyncMock(return_value=None))
    monkeypatch.setattr(facts_mod, "_find_conflict", AsyncMock(return_value=None))
    _install_embedder(monkeypatch)

    assert await facts_mod.add_fact(
        7, "偏好中文回答", category="preference", scope_type="global",
    ) is True

    insert_sql, insert_params = execute.await_args_list[0].args
    assert "status" in insert_sql and "version" in insert_sql
    # Category/status/version/supersedes, then topic and the derived one-line.
    assert insert_params[11:15] == ("preference", "active", 1, None)
    assert insert_params[15] == ""
    assert insert_params[16] == "偏好中文回答"


@pytest.mark.asyncio
async def test_add_fact_supersedes_previous_preference(monkeypatch):
    query = AsyncMock(side_effect=[[], [(0,)]])
    execute = AsyncMock(side_effect=[[], [(43,)], []])
    monkeypatch.setattr(facts_mod, "query", query)
    monkeypatch.setattr(facts_mod, "execute", execute)
    monkeypatch.setattr(facts_mod, "_is_semantic_duplicate", AsyncMock(return_value=None))
    monkeypatch.setattr(facts_mod, "_find_conflict", AsyncMock(return_value=(12, 1)))
    _install_embedder(monkeypatch)

    assert await facts_mod.add_fact(
        7, "偏好小步提交", category="preference",
    ) is True

    supersede_sql, supersede_params = execute.await_args_list[0].args
    assert "status = 'superseded'" in supersede_sql
    assert supersede_params == (12, 7)
    insert_params = execute.await_args_list[1].args[1]
    assert insert_params[11:15] == ("preference", "active", 2, 12)


@pytest.mark.asyncio
async def test_explicit_supersedes_wins_over_conflict_scan(monkeypatch):
    query = AsyncMock(side_effect=[
        [], [(0,)], [(12, "active", 1, "dev", "", "旧偏好")],
    ])
    execute = AsyncMock(side_effect=[[], [(44,)], []])
    find_conflict = AsyncMock(return_value=None)
    monkeypatch.setattr(facts_mod, "query", query)
    monkeypatch.setattr(facts_mod, "execute", execute)
    monkeypatch.setattr(facts_mod, "_is_semantic_duplicate", AsyncMock(return_value=None))
    monkeypatch.setattr(facts_mod, "_find_conflict", find_conflict)
    _install_embedder(monkeypatch)

    assert await facts_mod.add_fact(
        7, "以后用 ruff", scope_type="dev", supersedes_id=12,
    ) is True

    find_conflict.assert_not_awaited()
    old_sql, old_params = query.await_args_list[2].args
    assert "status = 'active'" in old_sql
    assert old_params == (12, 7)
    insert_params = execute.await_args_list[1].args[1]
    assert insert_params[13] == 2
    assert insert_params[14] == 12


@pytest.mark.asyncio
async def test_explicit_supersede_bypasses_semantic_dedup(monkeypatch):
    """A correction is near-identical by nature; explicit replaces must win."""
    query = AsyncMock(side_effect=[
        [], [(0,)], [(12, "active", 1, "dev", "", "用中文回答")],
    ])
    execute = AsyncMock(side_effect=[[], [(45,)], []])
    monkeypatch.setattr(facts_mod, "query", query)
    monkeypatch.setattr(facts_mod, "execute", execute)
    monkeypatch.setattr(facts_mod, "_is_semantic_duplicate", AsyncMock(return_value=12))
    monkeypatch.setattr(facts_mod, "_find_conflict", AsyncMock(return_value=None))
    _install_embedder(monkeypatch)

    assert await facts_mod.add_fact(
        7, "以后用英文回答", scope_type="dev", supersedes_id=12,
    ) is True

    supersede_sql, supersede_params = execute.await_args_list[0].args
    assert "status = 'superseded'" in supersede_sql
    assert supersede_params == (12, 7)
    insert_params = execute.await_args_list[1].args[1]
    assert insert_params[13] == 2
    assert insert_params[14] == 12


@pytest.mark.asyncio
async def test_edit_fact_reembeds_and_bumps_version(monkeypatch):
    current = {
        "id": 5, "content": "偏好 FastAPI", "hash": "h1", "scope_type": "dev",
        "scope_id": "", "version": 1, "status": "active", "category": "fact",
        "importance": 1.0, "ttl_days": 90,
    }
    query = AsyncMock(side_effect=[[(5, "偏好 FastAPI", "h1", "dev", "", 1, "active", "fact")], []])
    execute = AsyncMock(return_value=[(5,)])
    monkeypatch.setattr(facts_mod, "query", query)
    monkeypatch.setattr(facts_mod, "execute", execute)
    monkeypatch.setattr(facts_mod, "get_fact", AsyncMock(return_value=current))
    index = AsyncMock()
    monkeypatch.setattr(facts_mod.vector_store, "index_fact", index)
    _install_embedder(monkeypatch)

    result = await facts_mod.edit_fact(7, 5, content="偏好 Flask")

    assert result == current
    update_sql, update_params = execute.await_args.args
    assert "version = version + 1" in update_sql
    assert "RETURNING id" in update_sql
    assert update_params[0] == "偏好 Flask"
    index.assert_awaited_once()
    assert index.await_args.args[0] == 5


@pytest.mark.asyncio
async def test_edit_fact_rejects_duplicate_content(monkeypatch):
    query = AsyncMock(side_effect=[
        [(5, "偏好 FastAPI", "h1", "dev", "", 1, "active", "fact")],
        [(99,)],
    ])
    monkeypatch.setattr(facts_mod, "query", query)
    monkeypatch.setattr(facts_mod, "execute", AsyncMock())
    _install_embedder(monkeypatch)

    with pytest.raises(facts_mod.FactDuplicateError):
        await facts_mod.edit_fact(7, 5, content="偏好 FastAPI")


@pytest.mark.asyncio
async def test_edit_fact_requires_owner(monkeypatch):
    monkeypatch.setattr(facts_mod, "query", AsyncMock(return_value=[]))
    monkeypatch.setattr(facts_mod, "execute", AsyncMock())

    assert await facts_mod.edit_fact(7, 5, content="新的内容") is None


@pytest.mark.asyncio
async def test_fact_sources_returns_session_and_message(monkeypatch):
    query = AsyncMock(side_effect=[
        [(5, "偏好 FastAPI", "s1", 99, None, "调试会话", "user", "记住我喜欢 FastAPI")],
        [],
    ])
    monkeypatch.setattr(facts_mod, "query", query)

    result = await facts_mod.fact_sources(7, 5)

    assert result["source_session"]["title"] == "调试会话"
    assert result["source_message"]["role"] == "user"
    sql, params = query.await_args_list[0].args
    assert "f.user_id = %s" in sql
    assert params == (5, 7)


@pytest.mark.asyncio
async def test_retrieval_only_returns_active_facts(monkeypatch):
    rows = [(1, "偏好 FastAPI", [1.0, 0.0], 1.0)]
    query = AsyncMock(return_value=rows)
    execute = AsyncMock()
    monkeypatch.setattr(facts_mod, "query", query)
    monkeypatch.setattr(facts_mod, "execute", execute)
    _install_embedder(monkeypatch)

    await facts_mod.get_relevant_facts(1, "FastAPI")

    sql, _ = query.await_args.args
    assert "status = 'active'" in sql


@pytest.mark.asyncio
async def test_memory_api_edit_returns_updated_fact(monkeypatch):
    from fastapi import HTTPException

    from app.api.v1 import memory as memory_api
    from app.core.memory import policy as policy_mod
    from app.models.schemas import MemoryFactCreate, MemoryFactUpdate

    monkeypatch.setattr(
        memory_api.policy_mod, "get_policy",
        AsyncMock(return_value=policy_mod.DEFAULT_POLICY),
    )
    updated = {"id": 5, "content": "偏好 Flask", "status": "active"}
    edit = AsyncMock(return_value=updated)
    monkeypatch.setattr(memory_api.facts_mod, "edit_fact", edit)

    result = await memory_api.update_fact(
        5, MemoryFactUpdate(content="偏好 Flask"), user={"id": 7},
    )

    assert result == updated
    assert edit.await_args.kwargs["content"] == "偏好 Flask"

    edit.side_effect = facts_mod.FactDuplicateError("重复")
    with pytest.raises(HTTPException) as exc:
        await memory_api.update_fact(
            5, MemoryFactUpdate(content="偏好 Flask"), user={"id": 7},
        )
    assert exc.value.status_code == 409

    with pytest.raises(HTTPException) as exc:
        await memory_api.create_fact(
            MemoryFactCreate(content="仓库偏好", scope_type="repo"),
            user={"id": 7},
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_memory_api_sources_are_owner_scoped(monkeypatch):
    from fastapi import HTTPException

    from app.api.v1 import memory as memory_api

    monkeypatch.setattr(
        memory_api.facts_mod, "fact_sources", AsyncMock(return_value=None)
    )

    with pytest.raises(HTTPException) as exc:
        await memory_api.get_fact_sources(5, user={"id": 7})
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_list_facts_hides_inactive_by_default(monkeypatch):
    query = AsyncMock(return_value=[])
    monkeypatch.setattr(facts_mod, "query", query)

    await facts_mod.list_facts(7)

    sql, params = query.await_args.args
    assert "status = 'active'" in sql
    assert params == (7, 200)


@pytest.mark.asyncio
async def test_list_facts_can_include_archived(monkeypatch):
    query = AsyncMock(return_value=[])
    monkeypatch.setattr(facts_mod, "query", query)

    await facts_mod.list_facts(7, include_inactive=True)

    sql, _ = query.await_args.args
    assert "AND status = 'active'" not in sql

"""Reflection lessons: signal extraction, dedup, context retrieval, outcomes."""
from unittest.mock import AsyncMock

import pytest

from app.core.reflection import service as reflection


@pytest.mark.asyncio
async def test_extract_from_retried_task_stores_lesson(monkeypatch):
    async def fake_query(sql, params):
        if "FROM lessons WHERE user_id" in sql and "source_type" in sql:
            return []  # not yet known
        if "change_tasks" in sql:
            return [("t1", "加登录接口", "test_login 通过",
                     {"gate": "passed"}, 5, "r1")]
        if "FROM edits" in sql:
            return []
        return []

    inserts = []

    async def fake_execute(sql, params=None):
        inserts.append(sql)

    async def fake_llm_json(prompt, **kwargs):
        assert kwargs.get("purpose") == "utility"
        return {"kind": "practice", "content": "该仓库写接口必须同时更新契约文件"}

    async def fake_budget(**kwargs):
        return None

    monkeypatch.setattr(reflection, "query", fake_query)
    monkeypatch.setattr(reflection, "execute", fake_execute)
    monkeypatch.setattr(reflection, "llm_json", fake_llm_json)
    monkeypatch.setattr(reflection, "ensure_token_budget", fake_budget)

    result = await reflection.extract_lessons()
    assert result["extracted"] == 1
    assert any("INSERT INTO lessons" in sql for sql in inserts)
    assert any("DELETE FROM lessons" in sql for sql in inserts)  # stale cleanup ran


@pytest.mark.asyncio
async def test_extraction_skips_known_sources(monkeypatch):
    async def fake_query(sql, params):
        if "source_type" in sql and "FROM lessons" in sql:
            return [(1,)]  # already known
        if "change_tasks" in sql:
            return [("t1", "x", "y", {}, 5, "r1")]
        return []

    llm = AsyncMock()
    monkeypatch.setattr(reflection, "query", fake_query)
    monkeypatch.setattr(reflection, "execute", AsyncMock())
    monkeypatch.setattr(reflection, "llm_json", llm)
    result = await reflection.extract_lessons()
    assert result["extracted"] == 0
    llm.assert_not_awaited()


@pytest.mark.asyncio
async def test_store_lesson_validates_content(monkeypatch):
    execute = AsyncMock()
    monkeypatch.setattr(reflection, "execute", execute)
    assert await reflection._store_lesson(1, None, "s", "1", "practice", "太短") is False
    assert await reflection._store_lesson(
        1, None, "s", "2", "bogus", "这是一条足够长的有效教训内容" * 1) is True
    sql, params = execute.await_args.args
    assert "ON CONFLICT DO NOTHING" in sql
    assert params[3] == "practice"  # invalid kind normalized


@pytest.mark.asyncio
async def test_lessons_for_context_prefers_repo_specific(monkeypatch):
    async def fake_query(sql, params):
        assert "repo_id IS NULL OR repo_id = ANY" in sql
        return [("l1", "mistake", "别删测试")]
    monkeypatch.setattr(reflection, "query", fake_query)
    lessons = await reflection.lessons_for_context(7, ["r1"])
    assert lessons == [{"id": "l1", "kind": "mistake", "content": "别删测试"}]


@pytest.mark.asyncio
async def test_record_outcome_updates_counters(monkeypatch):
    execute = AsyncMock()
    monkeypatch.setattr(reflection, "execute", execute)
    await reflection.record_outcome(["l1"], ok=True)
    sql = execute.await_args_list[0].args[0]
    assert "hits = hits + 1" in sql
    await reflection.record_outcome(["l1"], ok=False)
    sql = execute.await_args_list[1].args[0]
    assert "misses = misses + 1" in sql

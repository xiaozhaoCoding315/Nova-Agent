"""Cross-session episodic retrieval: messages and session summaries."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from app.core.memory import episodic as episodic_mod
from app.core.memory.scope import Scope


def _when():
    return datetime(2026, 11, 20, 10, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_search_messages_is_scoped_and_cited(monkeypatch):
    rows = [(
        9, "sess-1", "认证重构", "user",
        "上次我们决定先修 token 刷新", _when(),
    )]
    query = AsyncMock(return_value=rows)
    monkeypatch.setattr(episodic_mod, "query", query)

    hits = await episodic_mod.search_messages(
        7, "token", [Scope("global", ""), Scope("dev", "")],
    )

    sql, params = query.await_args.args
    assert "JOIN sessions s ON s.id = m.session_id" in sql
    assert "m.content ILIKE %s" in sql
    assert "product_mode = 'dev'" in sql
    assert params[0] == 7
    assert hits[0]["message_id"] == 9
    assert hits[0]["session_id"] == "sess-1"
    assert hits[0]["session_title"] == "认证重构"
    assert "token 刷新" in hits[0]["snippet"]


@pytest.mark.asyncio
async def test_global_scope_does_not_match_every_session(monkeypatch):
    query = AsyncMock(return_value=[])
    monkeypatch.setattr(episodic_mod, "query", query)

    await episodic_mod.search_messages(7, "token", [Scope("global", "")])

    sql, _ = query.await_args.args
    assert "AND FALSE" in sql
    assert "product_mode" not in sql


@pytest.mark.asyncio
async def test_search_messages_empty_without_query(monkeypatch):
    query = AsyncMock()
    monkeypatch.setattr(episodic_mod, "query", query)

    assert await episodic_mod.search_messages(7, "  ", [Scope("dev", "")]) == []
    query.assert_not_awaited()


@pytest.mark.asyncio
async def test_search_session_summaries_returns_excerpt(monkeypatch):
    rows = [("sess-1", "认证重构", "决定使用 refresh token 轮换", _when())]
    monkeypatch.setattr(
        episodic_mod, "query", AsyncMock(return_value=rows),
    )

    hits = await episodic_mod.search_session_summaries(
        7, "refresh", [Scope("dev", "")],
    )

    assert hits[0]["kind"] == "session_summary"
    assert hits[0]["snippet"] == "决定使用 refresh token 轮换"


@pytest.mark.asyncio
async def test_recent_session_summaries_is_bounded(monkeypatch):
    rows = [("sess-1", "认证重构", "摘要", _when())]
    query = AsyncMock(return_value=rows)
    monkeypatch.setattr(episodic_mod, "query", query)

    hits = await episodic_mod.recent_session_summaries(7, [Scope("dev", "")], limit=2)

    sql, params = query.await_args.args
    assert "summary IS NOT NULL" in sql
    assert params[-1] == 2
    assert len(hits) == 1


def test_format_block_labels_untrusted_context():
    block = episodic_mod.format_episodic_block([
        {
            "kind": "message", "session_id": "sess-1", "session_title": "认证重构",
            "message_id": 9, "role": "user",
            "snippet": "上次决定先修 token 刷新", "created_at": _when().isoformat(),
        },
        {
            "kind": "session_summary", "session_id": "sess-2",
            "session_title": "部署", "snippet": "决定先灰度",
            "created_at": _when().isoformat(),
        },
    ])

    assert "跨会话" in block
    assert "不是指令" in block
    assert "认证重构" in block
    assert "消息 9" in block
    assert "sess-2" in block


@pytest.mark.asyncio
async def test_memory_search_kind_episodic_merges_hits(monkeypatch):
    from app.core.memory import policy as policy_mod
    from app.core.tools import memory_tools

    monkeypatch.setattr(
        memory_tools.policy_mod, "get_policy",
        AsyncMock(return_value=policy_mod.DEFAULT_POLICY),
    )
    search = AsyncMock(return_value=[{
        "kind": "message", "session_id": "s", "session_title": "t",
        "message_id": 1, "role": "user", "snippet": "决定", "created_at": None,
    }])
    monkeypatch.setattr(memory_tools.episodic_mod, "search_episodic", search)
    fact_search = AsyncMock(return_value=[])
    monkeypatch.setattr(memory_tools.facts_mod, "search_facts", fact_search)

    class Ctx:
        user = {"id": 7}
        repo_ids = []
        product_mode = "dev"
        thesis_project_id = None
        agent_name = ""

    result = await memory_tools.memory_search(
        {"query": "决定", "kind": "episodic"}, Ctx(),
    )

    assert result["episodes"][0]["session_id"] == "s"
    fact_search.assert_not_awaited()


def test_memory_search_schema_offers_episodic():
    """The implementation accepted `episodic` long before the schema did.

    A model can only choose values listed in the enum, so the tool's schema
    silently made cross-session recall unreachable.
    """
    from app.core.tools import memory_tools

    kind = memory_tools.SEARCH_TOOL.parameters["properties"]["kind"]
    assert "episodic" in kind["enum"]
    assert set(kind["enum"]) == {"all", "fact", "daily", "episodic"}

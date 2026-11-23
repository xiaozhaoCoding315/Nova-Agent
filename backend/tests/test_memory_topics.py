"""Deterministic topic index over active facts."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from app.core.memory import topics as topics_mod
from app.core.memory.scope import Scope


@pytest.mark.asyncio
async def test_build_topic_index_groups_and_redacts(monkeypatch):
    row = (
        "数据库", "dev", "", 3, datetime(2026, 11, 21, tzinfo=timezone.utc),
        ["使用 PostgreSQL", "迁移用 alembic", "密码 sk-abcdefghijklmnopqrstuvwxyz"],
    )
    query = AsyncMock(return_value=[row])
    monkeypatch.setattr(topics_mod, "query", query)

    items = await topics_mod.build_topic_index(7)

    assert items[0]["topic"] == "数据库"
    assert items[0]["count"] == 3
    assert len(items[0]["samples"]) == 3
    assert "sk-abcdefghijklmnopqrstuvwxyz" not in items[0]["samples"][2]


@pytest.mark.asyncio
async def test_build_topic_index_filters_scopes(monkeypatch):
    query = AsyncMock(return_value=[])
    monkeypatch.setattr(topics_mod, "query", query)

    await topics_mod.build_topic_index(
        7, [Scope("global", ""), Scope("repo", "r1")], limit=5,
    )

    sql, params = query.await_args.args
    assert "(scope_type = %s AND scope_id = %s)" in sql
    assert params[:5] == (7, "global", "", "repo", "r1")
    assert params[-1] == 5


@pytest.mark.asyncio
async def test_count_topics(monkeypatch):
    monkeypatch.setattr(
        topics_mod, "query", AsyncMock(return_value=[(9,)]),
    )

    assert await topics_mod.count_topics() == 9


def test_format_topic_block_is_bounded():
    block = topics_mod.format_topic_block([
        {"topic": "数据库", "count": 2, "samples": ["PostgreSQL", "alembic"]},
    ])

    assert "记忆主题索引" in block
    assert "数据库（2 条）" in block
    assert "PostgreSQL" in block


def test_memory_topics_endpoint(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.v1 import memory as memory_api
    from app.core.security.auth import get_current_user

    app = FastAPI()
    app.include_router(memory_api.router)
    app.dependency_overrides[get_current_user] = lambda: {"id": 7}
    monkeypatch.setattr(
        memory_api.topics_mod, "build_topic_index",
        AsyncMock(return_value=[{
            "topic": "数据库", "scope_type": "dev", "scope_id": "",
            "count": 2, "updated_at": None, "samples": ["PostgreSQL"],
        }]),
    )

    response = TestClient(app).get("/memory/topics")

    assert response.status_code == 200
    assert response.json()[0]["topic"] == "数据库"

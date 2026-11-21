"""Thesis projects may only link repos the same user owns."""
from unittest.mock import AsyncMock

import pytest

from app.core.thesis import service

PROJECT_ID = "22222222-2222-2222-2222-222222222222"
REPO_ID = "11111111-1111-1111-1111-111111111111"


@pytest.mark.asyncio
async def test_link_rejects_foreign_repo(monkeypatch):
    monkeypatch.setattr(service, "query", AsyncMock(return_value=[]))
    with pytest.raises(ValueError, match="工程项目不存在"):
        await service.update_project(7, PROJECT_ID, source_repo_id=REPO_ID)
    with pytest.raises(ValueError, match="工程项目不存在"):
        await service.create_project(7, title="示例论文", source_repo_id=REPO_ID)


@pytest.mark.asyncio
async def test_empty_repo_id_detaches_without_lookup(monkeypatch):
    lookup = AsyncMock(side_effect=AssertionError("detach must not query repos"))
    execute = AsyncMock(return_value=[])
    monkeypatch.setattr(service, "query", lookup)
    monkeypatch.setattr(service, "execute", execute)
    monkeypatch.setattr(
        service, "get_project", AsyncMock(return_value={"id": PROJECT_ID}),
    )

    project = await service.update_project(7, PROJECT_ID, source_repo_id="")

    sql, params = execute.await_args.args
    assert "source_repo_id = NULL" in sql
    assert REPO_ID not in params
    assert project == {"id": PROJECT_ID}


@pytest.mark.asyncio
async def test_owned_repo_can_be_linked(monkeypatch):
    monkeypatch.setattr(service, "query", AsyncMock(return_value=[(1,)]))
    execute = AsyncMock(return_value=[])
    monkeypatch.setattr(service, "execute", execute)
    monkeypatch.setattr(
        service, "get_project", AsyncMock(return_value={"id": PROJECT_ID}),
    )

    await service.update_project(7, PROJECT_ID, source_repo_id=REPO_ID)

    sql, params = execute.await_args.args
    assert "source_repo_id = %s" in sql
    assert params[0] == REPO_ID

"""Memory export/purge endpoints, settings API and storage-time redaction."""
from unittest.mock import AsyncMock

import pytest

from app.core.memory import policy as policy_mod
from app.core.memory import session as session_mod
from app.core.security.redaction import REDACTED


def _client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.v1 import memory as memory_api
    from app.api.v1 import settings_memory as settings_api
    from app.core.security.auth import get_current_user

    app = FastAPI()
    app.include_router(memory_api.router)
    app.include_router(settings_api.router)
    app.dependency_overrides[get_current_user] = lambda: {"id": 7}
    return TestClient(app), memory_api, settings_api


def test_memory_settings_get_uses_defaults(monkeypatch):
    client, _, _ = _client()
    monkeypatch.setattr(
        policy_mod, "get_policy", AsyncMock(return_value=policy_mod.DEFAULT_POLICY),
    )

    response = client.get("/settings/memory")

    assert response.status_code == 200
    assert response.json()["auto_memory"] is True
    assert response.json()["default_scope"] == "dev"


def test_memory_settings_put_rejects_empty(monkeypatch):
    client, _, _ = _client()

    response = client.put("/settings/memory", json={})

    assert response.status_code == 400


def test_memory_settings_put_updates(monkeypatch):
    client, _, _ = _client()
    updated = policy_mod.MemoryPolicy(
        auto_memory=False, retention_days=14, default_scope="global",
    )
    monkeypatch.setattr(policy_mod, "update_policy", AsyncMock(return_value=updated))
    monkeypatch.setattr(policy_mod, "log_audit", AsyncMock(), raising=False)
    monkeypatch.setattr(
        "app.api.v1.settings_memory.log_audit", AsyncMock(),
    )

    response = client.put(
        "/settings/memory",
        json={"auto_memory": False, "retention_days": 14},
    )

    assert response.status_code == 200
    assert response.json()["auto_memory"] is False
    assert response.json()["retention_days"] == 14


def test_export_json_includes_facts_daily_and_audit(monkeypatch):
    client, memory_api, _ = _client()
    fact = {
        "id": 1, "content": "偏好中文", "scope_type": "global", "scope_id": "",
        "category": "preference", "status": "active", "version": 1,
        "source_session_id": "s1", "source_message_id": 9,
        "supersedes_id": None, "merged_into_id": None,
    }
    daily_rows = [("2026-11-21", "完成 P1", 8, None, None, "dev", "")]
    lesson_rows = [("practice", "先读再改", None)]
    monkeypatch.setattr(
        memory_api.facts_mod, "list_facts", AsyncMock(return_value=[fact]),
    )
    monkeypatch.setattr(
        memory_api, "query", AsyncMock(side_effect=[daily_rows, lesson_rows]),
    )
    audit = AsyncMock()
    monkeypatch.setattr(memory_api, "log_audit", audit)

    response = client.get("/memory/export")

    assert response.status_code == 200
    payload = response.json()
    assert payload["facts"][0]["content"] == "偏好中文"
    assert payload["daily"][0]["day"] == "2026-11-21"
    assert payload["lessons"][0]["content"] == "先读再改"
    audit.assert_awaited_once()


def test_export_markdown_is_attachment(monkeypatch):
    client, memory_api, _ = _client()
    monkeypatch.setattr(
        memory_api.facts_mod, "list_facts", AsyncMock(return_value=[{
            "id": 1, "content": "偏好中文", "scope_type": "global",
            "scope_id": "", "category": "preference", "status": "active",
            "version": 1, "source_session_id": None, "source_message_id": None,
            "supersedes_id": None, "merged_into_id": None,
        }]),
    )
    monkeypatch.setattr(memory_api, "query", AsyncMock(return_value=[]))
    monkeypatch.setattr(memory_api, "log_audit", AsyncMock())

    response = client.get("/memory/export?format=markdown")

    assert response.status_code == 200
    assert "text/markdown" in response.headers["content-type"]
    assert "attachment" in response.headers["content-disposition"]
    assert "偏好中文" in response.text


def test_purge_requires_confirmation():
    client, _, _ = _client()

    response = client.delete("/memory/all")

    assert response.status_code == 400


def test_purge_deletes_memory_and_messages(monkeypatch):
    client, memory_api, _ = _client()
    execute = AsyncMock(side_effect=[
        [(1,), (2,)],   # facts
        [("2026-11-21",)],  # daily
        [(3,)],         # lessons
        [],             # compaction records
        [(10,), (11,)],  # messages
        [],             # session reset
    ])
    monkeypatch.setattr(memory_api, "execute", execute)
    monkeypatch.setattr(memory_api, "log_audit", AsyncMock())

    response = client.delete("/memory/all?confirm=true")

    assert response.status_code == 200
    assert response.json() == {
        "ok": True, "facts": 2, "daily": 1, "lessons": 1, "messages": 2,
    }
    assert "DELETE FROM messages" in execute.await_args_list[4].args[0]


def test_purge_scoped_leaves_messages(monkeypatch):
    client, memory_api, _ = _client()
    execute = AsyncMock(side_effect=[[(1,)], [("2026-11-21",)]])
    monkeypatch.setattr(memory_api, "execute", execute)
    monkeypatch.setattr(memory_api, "log_audit", AsyncMock())

    response = client.delete("/memory/all?confirm=true&scope_type=dev")

    assert response.status_code == 200
    assert response.json()["messages"] == 0
    assert all("messages" not in call.args[0] for call in execute.await_args_list)


@pytest.mark.asyncio
async def test_add_message_redacts_secrets_before_insert(monkeypatch):
    execute = AsyncMock(side_effect=[[(1,)], []])
    monkeypatch.setattr(session_mod, "execute", execute)

    await session_mod.add_message(
        "s1", "user", "token=sk-abcdefghijklmnopqrstuvwxyz",
        tool_json={"command": "export KEY=supersecretvalue"},
    )

    _, params = execute.await_args_list[0].args
    assert "sk-abcdefghijklmnopqrstuvwxyz" not in params[2]
    assert REDACTED in params[2] or "REDACTED" in params[2]
    assert "supersecretvalue" not in params[3]


@pytest.mark.asyncio
async def test_set_summary_redacts_before_store(monkeypatch):
    execute = AsyncMock()
    monkeypatch.setattr(session_mod, "execute", execute)

    await session_mod.set_summary("s1", "key=sk-abcdefghijklmnopqrstuvwxyz", 3)

    _, params = execute.await_args.args
    assert "sk-abcdefghijklmnopqrstuvwxyz" not in params[0]

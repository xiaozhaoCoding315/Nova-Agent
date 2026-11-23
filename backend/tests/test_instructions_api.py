"""Layered instruction settings API."""
from unittest.mock import AsyncMock

from app.core.memory import instructions as instructions_mod


def _client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.v1 import settings_instructions as api_mod
    from app.core.security.auth import get_current_user

    app = FastAPI()
    app.include_router(api_mod.router)
    app.dependency_overrides[get_current_user] = lambda: {"id": 7}
    return TestClient(app), api_mod


def _instruction(**overrides):
    row = {
        "id": 1, "level": "user", "scope_type": "global", "scope_id": "",
        "name": "习惯", "content": "先写测试", "paths": [], "enabled": True,
        "priority": 100, "created_at": None, "updated_at": None,
    }
    row.update(overrides)
    return row


def test_list_instructions(monkeypatch):
    client, api_mod = _client()
    monkeypatch.setattr(
        api_mod.instructions_mod, "list_instructions",
        AsyncMock(return_value=[_instruction()]),
    )

    response = client.get("/settings/instructions")

    assert response.status_code == 200
    assert response.json()[0]["name"] == "习惯"


def test_list_rejects_unknown_level(monkeypatch):
    client, api_mod = _client()
    monkeypatch.setattr(
        api_mod.instructions_mod, "list_instructions",
        AsyncMock(side_effect=ValueError("指令层级只能是 org、user 或 project")),
    )

    response = client.get("/settings/instructions?level=nope")

    assert response.status_code == 400


def test_create_instruction_audits(monkeypatch):
    client, api_mod = _client()
    monkeypatch.setattr(
        api_mod.instructions_mod, "create_instruction",
        AsyncMock(return_value=_instruction()),
    )
    audit = AsyncMock()
    monkeypatch.setattr(api_mod, "log_audit", audit)

    response = client.post(
        "/settings/instructions",
        json={"level": "user", "content": "先写测试"},
    )

    assert response.status_code == 200
    assert response.json()["id"] == 1
    audit.assert_awaited_once()


def test_create_instruction_maps_value_error(monkeypatch):
    client, api_mod = _client()
    monkeypatch.setattr(
        api_mod.instructions_mod, "create_instruction",
        AsyncMock(side_effect=ValueError("指令内容不能为空")),
    )

    response = client.post(
        "/settings/instructions",
        json={"level": "user", "content": "x"},
    )

    assert response.status_code == 400
    assert "不能为空" in response.json()["detail"]


def test_update_missing_instruction_returns_404(monkeypatch):
    client, api_mod = _client()
    monkeypatch.setattr(
        api_mod.instructions_mod, "update_instruction",
        AsyncMock(side_effect=instructions_mod.InstructionNotFound("指令不存在")),
    )
    monkeypatch.setattr(api_mod, "log_audit", AsyncMock())

    response = client.put("/settings/instructions/9", json={"enabled": False})

    assert response.status_code == 404


def test_update_requires_a_field(monkeypatch):
    client, _ = _client()

    response = client.put("/settings/instructions/9", json={})

    assert response.status_code == 400


def test_delete_instruction(monkeypatch):
    client, api_mod = _client()
    monkeypatch.setattr(
        api_mod.instructions_mod, "delete_instruction",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(api_mod, "log_audit", AsyncMock())

    response = client.delete("/settings/instructions/3")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_delete_missing_instruction_returns_404(monkeypatch):
    client, api_mod = _client()
    monkeypatch.setattr(
        api_mod.instructions_mod, "delete_instruction", AsyncMock(return_value=False),
    )

    response = client.delete("/settings/instructions/3")

    assert response.status_code == 404

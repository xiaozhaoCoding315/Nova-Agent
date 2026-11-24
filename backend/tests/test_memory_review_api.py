"""Memory review queue API."""
from unittest.mock import AsyncMock


def _client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.v1 import memory as memory_api
    from app.core.security.auth import get_current_user

    app = FastAPI()
    app.include_router(memory_api.router)
    app.dependency_overrides[get_current_user] = lambda: {"id": 7}
    return TestClient(app), memory_api


def _item(**overrides):
    item = {
        "id": 1, "kind": "high_risk_fact", "fact_id": 5,
        "target_fact_id": None, "status": "pending", "reason": "部署发布",
        "payload": {}, "created_at": None, "content": "部署前不用问我",
        "one_line": "部署前不用问我", "category": "fact",
        "scope_type": "dev", "scope_id": "", "target_content": None,
    }
    item.update(overrides)
    return item


def test_list_review_items(monkeypatch):
    client, api_mod = _client()
    monkeypatch.setattr(
        api_mod.review_mod, "list_items", AsyncMock(return_value=[_item()]),
    )

    response = client.get("/memory/review")

    assert response.status_code == 200
    assert response.json()[0]["kind"] == "high_risk_fact"


def test_list_rejects_bad_status(monkeypatch):
    client, api_mod = _client()
    monkeypatch.setattr(
        api_mod.review_mod, "list_items",
        AsyncMock(side_effect=ValueError("复核状态只能是 pending")),
    )

    response = client.get("/memory/review?status=done")

    assert response.status_code == 400


def test_approve_returns_resolved_item(monkeypatch):
    client, api_mod = _client()
    monkeypatch.setattr(
        api_mod.review_mod, "resolve",
        AsyncMock(return_value=_item(status="approved")),
    )

    response = client.post("/memory/review/1/approve")

    assert response.status_code == 200
    assert response.json()["status"] == "approved"


def test_resolve_missing_item_returns_404(monkeypatch):
    client, api_mod = _client()
    monkeypatch.setattr(
        api_mod.review_mod, "resolve", AsyncMock(return_value=None),
    )

    response = client.post("/memory/review/1/reject")

    assert response.status_code == 404

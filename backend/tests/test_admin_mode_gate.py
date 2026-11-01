"""Admin API is server-only: local mode returns 404 before auth/body parsing."""
import pytest

from app.config import settings

_ADMIN_CASES = (
    ("get", "/api/v1/admin/usage/sources", {}),
    ("get", "/api/v1/admin/users", {}),
    ("post", "/api/v1/admin/users", {"json": {"username": "tester", "password": "secret"}}),
    ("patch", "/api/v1/admin/users/2", {"json": {"status": "disabled"}}),
    ("post", "/api/v1/admin/users/2/password", {"json": {"new_password": "secret"}}),
    ("delete", "/api/v1/admin/users/2", {}),
    ("get", "/api/v1/admin/invites", {}),
    ("post", "/api/v1/admin/invites", {"json": {"note": "x"}}),
    ("delete", "/api/v1/admin/invites/2", {}),
)


def _router_client(user=None):
    """Real API router mounted at /api/v1; auth override only when given."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.v1.router import api_router
    from app.core.security.auth import get_current_user

    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    if user is not None:
        app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


@pytest.mark.parametrize("method,path,kwargs", _ADMIN_CASES)
def test_local_mode_admin_routes_return_404_before_auth(monkeypatch, method, path, kwargs):
    monkeypatch.setattr(settings, "nova_mode", "local")
    client = _router_client()  # no auth override: the gate must win over 401

    response = getattr(client, method)(path, **kwargs)

    assert response.status_code == 404, (method, path, response.text)
    assert "本地模式" in response.json()["detail"]


def test_local_mode_admin_rejects_before_body_parsing(monkeypatch):
    monkeypatch.setattr(settings, "nova_mode", "local")
    client = _router_client()

    response = client.post(
        "/api/v1/admin/users",
        content="{not-json",
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 404
    assert "本地模式" in response.json()["detail"]


@pytest.mark.parametrize("method,path,kwargs", _ADMIN_CASES)
def test_server_mode_admin_routes_still_require_auth(monkeypatch, method, path, kwargs):
    monkeypatch.setattr(settings, "nova_mode", "server")
    client = _router_client()

    response = getattr(client, method)(path, **kwargs)

    assert response.status_code == 401, (method, path, response.text)


@pytest.mark.parametrize("method,path,kwargs", _ADMIN_CASES)
def test_server_mode_admin_routes_still_reject_non_admin(monkeypatch, method, path, kwargs):
    monkeypatch.setattr(settings, "nova_mode", "server")
    client = _router_client({"id": 1, "role": "demo"})

    response = getattr(client, method)(path, **kwargs)

    assert response.status_code == 403, (method, path, response.text)

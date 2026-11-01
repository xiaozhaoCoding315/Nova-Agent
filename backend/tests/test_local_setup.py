"""首次启动接口：注册本地项目并把 LLM Key 加密存储，绝不回显明文。"""
import json
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.api.v1 import local_setup
from app.config import settings
from app.core.llm import user_settings
from app.core.llm.user_settings import decrypt_key, encrypt_key
from app.models.schemas import LocalSetupIn


def _repo() -> dict:
    return {
        "id": "00000000-0000-0000-0000-000000000001",
        "name": "demo",
        "source": "local:D:/code/demo",
        "status": "pending",
        "kind": "import",
        "origin": "local",
        "error": None,
        "stats": {},
        "created_at": None,
        "smoke": None,
    }


def _dumped(value) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _api_client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.core.security.auth import get_current_user

    app = FastAPI()
    app.include_router(local_setup.router)
    app.dependency_overrides[get_current_user] = lambda: {"id": 1, "role": "local"}
    return TestClient(app)


@pytest.mark.asyncio
async def test_setup_status_unconfigured(monkeypatch):
    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(settings, "nova_data_dir", "D:/Nova")
    query = AsyncMock(side_effect=[[(0,)], []])
    monkeypatch.setattr(local_setup, "query", query)
    status = await local_setup.get_local_setup({"id": 1})
    assert status.configured is False
    assert status.project_count == 0
    assert status.has_llm_key is False


@pytest.mark.asyncio
async def test_setup_status_configured(monkeypatch):
    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(settings, "nova_data_dir", "D:/Nova")
    monkeypatch.setattr(
        local_setup, "query",
        AsyncMock(side_effect=[
            [(2,)],
            [("zhipu", "glm-4.7-flash", "encrypted", True)],
        ]),
    )
    status = await local_setup.get_local_setup({"id": 1})
    assert status.configured is True
    assert status.has_llm_key is True
    assert status.default_provider == "zhipu"
    assert status.default_model == "glm-4.7-flash"


@pytest.mark.asyncio
async def test_post_setup_saves_key_but_never_returns_it(monkeypatch, tmp_path):
    project = tmp_path / "demo"
    project.mkdir()
    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(settings, "nova_data_dir", str(tmp_path / "Nova"))
    save = AsyncMock(return_value={})
    register = AsyncMock(return_value=_repo())
    audit = AsyncMock(return_value=None)
    monkeypatch.setattr(local_setup, "save_user_config", save)
    monkeypatch.setattr(local_setup, "register_local_project", register)
    monkeypatch.setattr(local_setup, "log_audit", audit)
    body = LocalSetupIn(
        project_path=str(project),
        provider="zhipu",
        model="glm-4.7-flash",
        api_key="sk-test-secret-1234",
    )
    result = await local_setup.run_local_setup(body, {"id": 1})
    assert result.ok is True
    assert result.has_key is True
    assert result.repo.origin == "local"
    dumped = json.dumps(result.model_dump(mode="json"), ensure_ascii=False)
    assert "sk-test-secret-1234" not in dumped
    assert "api_key" not in dumped
    save.assert_awaited_once()
    assert save.await_args.kwargs["api_key"] == "sk-test-secret-1234"
    assert "api_key" not in audit.await_args.kwargs["details"]
    assert "sk-test-secret-1234" not in _dumped(audit.await_args.kwargs)


@pytest.mark.asyncio
async def test_post_setup_requires_key_on_first_run(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(settings, "nova_data_dir", str(tmp_path / "Nova"))
    monkeypatch.setattr(local_setup, "query", AsyncMock(return_value=[]))
    body = LocalSetupIn(project_path=str(tmp_path), api_key=None)
    with pytest.raises(HTTPException) as exc:
        await local_setup.run_local_setup(body, {"id": 1})
    assert exc.value.status_code == 400
    assert "API Key" in exc.value.detail


@pytest.mark.asyncio
async def test_local_setup_rejects_server_mode(monkeypatch):
    monkeypatch.setattr(settings, "nova_mode", "server")
    with pytest.raises(HTTPException) as exc:
        await local_setup.get_local_setup({"id": 1})
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        await local_setup.run_local_setup(
            LocalSetupIn(project_path="D:/code/demo"), {"id": 1}
        )
    assert exc.value.status_code == 404

    client = _api_client()
    assert client.get("/local/setup").status_code == 404
    response = client.post("/local/setup", json={"project_path": "D:/code/demo"})
    assert response.status_code == 404
    assert "本地模式" in response.json()["detail"]


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


def test_server_mode_returns_404_before_auth(monkeypatch):
    monkeypatch.setattr(settings, "nova_mode", "server")
    client = _router_client()  # no auth override: the gate must win over 401

    response = client.get("/api/v1/local/setup")
    assert response.status_code == 404
    assert "本地模式" in response.json()["detail"]

    response = client.post("/api/v1/local/setup")
    assert response.status_code == 404
    assert "本地模式" in response.json()["detail"]

    response = client.post(
        "/api/v1/local/setup",
        json={"project_path": "D:/code/demo", "api_key": "sk-dummy-0001"},
    )
    assert response.status_code == 404


def test_server_mode_returns_404_before_body_validation(monkeypatch):
    monkeypatch.setattr(settings, "nova_mode", "server")
    client = _router_client()  # no auth override

    secret = "sk-oversized-secret-1234"
    response = client.post(
        "/api/v1/local/setup",
        json={"project_path": "D:/code/demo", "api_key": secret * 200},
    )
    assert response.status_code == 404
    assert secret not in response.text

    malformed = '{"project_path": "D:/code/demo", "api_key": "' + secret
    response = client.post(
        "/api/v1/local/setup",
        content=malformed,
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 404
    assert secret not in response.text


def test_local_validation_errors_hide_api_key(monkeypatch):
    monkeypatch.setattr(settings, "nova_mode", "local")
    client = _router_client({"id": 1, "role": "local"})
    secret = "sk-local-validation-secret-1234"
    oversized = "sk-" + "a" * 4001

    # (json payload, raw body) — one of the two is set per case.
    cases = [
        ({"api_key": secret}, None),                     # missing project_path
        ({"project_path": "D:/code/demo", "api_key": oversized}, None),
        ([secret], None),                                # wrong top-level type
        (None, '{"project_path": "D:/code/demo", "api_key": "' + secret),
        (None, '{"project_path": "D:/code/demo", "api_key": "' + oversized + '"}'),
    ]
    for payload, raw in cases:
        if raw is not None:
            response = client.post(
                "/api/v1/local/setup",
                content=raw,
                headers={"content-type": "application/json"},
            )
        else:
            response = client.post("/api/v1/local/setup", json=payload)
        assert response.status_code == 400
        assert response.json() == {"detail": "请求参数无效"}
        assert secret not in response.text
        assert oversized not in response.text


def test_server_mode_other_validation_errors_stay_422(monkeypatch):
    monkeypatch.setattr(settings, "nova_mode", "server")

    response = _router_client().post("/api/v1/auth/login", json={})

    assert response.status_code == 422


def test_local_setup_defaults_are_zhipu_flash():
    body = LocalSetupIn(project_path="D:/code/demo")
    assert body.provider == "zhipu"
    assert body.model == "glm-4.7-flash"
    assert body.api_key is None


@pytest.mark.asyncio
async def test_setup_status_never_exposes_key(monkeypatch):
    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(settings, "nova_data_dir", "D:/Nova")
    secret = "sk-status-secret-0001"
    monkeypatch.setattr(
        local_setup, "query",
        AsyncMock(side_effect=[
            [(1,)],
            [("zhipu", "glm-4.7-flash", encrypt_key(secret), True)],
        ]),
    )
    status = await local_setup.get_local_setup({"id": 1})
    assert status.has_llm_key is True
    assert secret not in _dumped(status.model_dump(mode="json"))


@pytest.mark.asyncio
async def test_post_setup_unknown_provider_maps_to_400(monkeypatch, tmp_path):
    project = tmp_path / "demo"
    project.mkdir()
    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(settings, "nova_data_dir", str(tmp_path / "Nova"))
    register = AsyncMock(return_value=_repo())
    monkeypatch.setattr(local_setup, "register_local_project", register)
    body = LocalSetupIn(
        project_path=str(project),
        provider="not-a-provider",
        api_key="sk-unknown-provider",
    )
    with pytest.raises(HTTPException) as exc:
        await local_setup.run_local_setup(body, {"id": 1})
    assert exc.value.status_code == 400
    assert "模型服务商" in exc.value.detail
    assert "sk-unknown-provider" not in exc.value.detail
    register.assert_not_awaited()


class _CredentialStore:
    """Minimal in-memory stand-in for user_llm_providers."""

    def __init__(self, encrypted: str):
        self.provider = "zhipu"
        self.base_url = "https://open.bigmodel.cn/api/paas/v4"
        self.model = "glm-4.7-flash"
        self.enc = encrypted

    async def query(self, sql, params=None):
        if "api_key_enc FROM user_llm_providers" in sql:
            return [(self.enc,)]
        if "WHERE user_id = %s AND is_default LIMIT 1" in sql:
            return [(1,)]
        if "SELECT provider, base_url, model, api_key_enc" in sql:
            return [(
                self.provider, self.base_url, self.model, self.enc,
                None, "", True, None,
            )]
        raise AssertionError(f"unexpected user_settings query: {sql}")

    async def execute(self, sql, params=None):
        if "INSERT INTO user_llm_providers" in sql:
            self.provider, self.model, self.enc = params[1], params[3], params[4]
        return []


@pytest.mark.asyncio
async def test_post_setup_second_run_without_key_preserves_stored_credential(
    monkeypatch, tmp_path
):
    project = tmp_path / "demo"
    project.mkdir()
    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(settings, "nova_data_dir", str(tmp_path / "Nova"))
    existing = "sk-existing-secret-5678"
    store = _CredentialStore(encrypt_key(existing))
    monkeypatch.setattr(user_settings, "query", store.query)
    monkeypatch.setattr(user_settings, "execute", store.execute)
    monkeypatch.setattr(
        local_setup, "register_local_project", AsyncMock(return_value=_repo())
    )
    monkeypatch.setattr(local_setup, "log_audit", AsyncMock(return_value=None))

    async def api_query(sql, params=None):
        if "count(*)" in sql:
            return [(1,)]
        if "api_key_enc <> ''" in sql:
            return [(1,)] if store.enc else []
        if "SELECT provider, model, api_key_enc, is_default" in sql:
            return [(store.provider, store.model, store.enc, True)]
        raise AssertionError(f"unexpected api query: {sql}")

    monkeypatch.setattr(local_setup, "query", api_query)

    result = await local_setup.run_local_setup(
        LocalSetupIn(project_path=str(project)), {"id": 1}
    )

    assert result.has_key is True
    assert store.enc
    assert decrypt_key(store.enc) == existing
    status = await local_setup.get_local_setup({"id": 1})
    assert status.has_llm_key is True
    assert status.default_provider == "zhipu"
    assert existing not in _dumped(result.model_dump(mode="json"))


@pytest.mark.parametrize("kind", ["data_root", "ancestor", "unc", "dotdot"])
def test_post_setup_rejects_invalid_paths(monkeypatch, tmp_path, kind):
    data = tmp_path / "NovaData"
    data.mkdir()
    (data / "users").mkdir()
    project = tmp_path / "demo"
    project.mkdir()
    monkeypatch.setattr(settings, "nova_mode", "local")
    monkeypatch.setattr(settings, "nova_data_dir", str(data))
    secret = "sk-invalid-path-secret-9999"
    paths = {
        "data_root": str(data),
        "ancestor": str(tmp_path),
        "unc": r"\\server\share\repo",
        "dotdot": str(project / ".." / "NovaData"),
    }

    response = _api_client().post(
        "/local/setup",
        json={"project_path": paths[kind], "api_key": secret},
    )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail
    assert "数据目录" in detail or "UNC" in detail
    assert secret not in response.text


def test_local_setup_routes_are_in_openapi_contract():
    from app.main import app

    spec = app.openapi()
    for method in ("get", "post"):
        operation = spec["paths"]["/api/v1/local/setup"][method]
        schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
        assert schema
        assert "security" not in operation

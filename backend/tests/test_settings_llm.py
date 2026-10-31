"""Per-user LLM settings: schema bounds and HTTP endpoints (no live DB)."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.v1 import settings_llm
from app.core.security.auth import get_current_user
from app.models.schemas import (
    LlmCredentialUpdate,
    LlmOverrides,
    LlmProviderOut,
    LlmSettingsUpdate,
)

USER = {"id": 7, "role": "user", "is_guest": False}
STORED_KEY = "stored-plain-key-wxyz"
KEY_HINT = "••••wxyz"


def _config(**overrides) -> dict:
    """A stored-credential row as ``user_settings`` returns it, key included."""
    config = {
        "provider": "zhipu",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4.7-flash",
        "api_key": STORED_KEY,
        "key_hint": KEY_HINT,
        "key_error": "",
        "context_window": None,
        "reasoning_effort": "",
        "is_default": True,
        "updated_at": datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
    }
    config.update(overrides)
    return config


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(settings_llm.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: dict(USER)
    # No ``with`` block: no lifespan runs, so the main app's DB init is skipped.
    return TestClient(app)


def test_provider_payload_exposes_ui_fields():
    item = LlmProviderOut(
        id="zhipu", label="智谱 GLM", group="domestic", kind="openai",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        models=["glm-4.7-flash"], docs_url="", free_tier=True,
        supports_tools=True, supports_reasoning=True,
        supports_temperature=True, context_window=131072,
        base_url_locked=True, env_key="ZHIPU_API_KEY", icon="zhipu",
    )
    assert item.icon == "zhipu"
    assert item.base_url_locked is True


def test_credential_update_accepts_blank_key_for_keep():
    body = LlmCredentialUpdate(model="glm-4.7-flash", api_key=None, is_default=True)
    assert body.api_key is None
    assert body.is_default is True


def test_overrides_reject_out_of_range_values():
    with pytest.raises(ValidationError):
        LlmOverrides(temperature=3)
    with pytest.raises(ValidationError):
        LlmOverrides(context_window=100)
    assert LlmOverrides(provider="zhipu", reasoning_effort="high").provider == "zhipu"


def test_overrides_context_window_boundaries():
    assert LlmOverrides().context_window is None
    assert LlmOverrides(context_window=None).context_window is None
    assert LlmOverrides(context_window=0).context_window == 0
    assert LlmOverrides(context_window=2048).context_window == 2048
    assert LlmOverrides(context_window=10_000_000).context_window == 10_000_000
    with pytest.raises(ValidationError):
        LlmOverrides(context_window=2047)
    with pytest.raises(ValidationError):
        LlmOverrides(context_window=10_000_001)


def test_overrides_temperature_boundaries():
    assert LlmOverrides(temperature=0).temperature == 0
    assert LlmOverrides(temperature=2).temperature == 2
    with pytest.raises(ValidationError):
        LlmOverrides(temperature=-0.1)
    with pytest.raises(ValidationError):
        LlmOverrides(temperature=2.1)


@pytest.mark.parametrize(
    ("schema", "payload"),
    [
        (LlmCredentialUpdate, {"model": "glm-4.7-flash"}),
        (LlmSettingsUpdate, {"provider": "zhipu", "model": "glm-4.7-flash"}),
    ],
)
def test_update_schemas_share_context_window_bounds(schema, payload):
    assert schema(**payload).context_window is None
    assert schema(**payload, context_window=0).context_window == 0
    assert schema(**payload, context_window=2048).context_window == 2048
    assert schema(**payload, context_window=10_000_000).context_window == 10_000_000
    with pytest.raises(ValidationError):
        schema(**payload, context_window=2047)
    with pytest.raises(ValidationError):
        schema(**payload, context_window=10_000_001)


def test_list_credentials_never_exposes_raw_key(client, monkeypatch):
    monkeypatch.setattr(
        settings_llm, "list_user_configs", AsyncMock(return_value=[_config()]),
    )

    response = client.get("/api/v1/settings/llm/credentials")

    assert response.status_code == 200
    item = response.json()[0]
    assert "api_key" not in item
    assert item["has_key"] is True
    assert item["key_hint"] == KEY_HINT
    assert item["provider"] == "zhipu"
    assert item["label"] == "智谱 GLM"


def test_save_credential_returns_masked_view(client, monkeypatch):
    save = AsyncMock(return_value=_config(model="glm-4.6", is_default=False))
    monkeypatch.setattr(settings_llm, "save_user_config", save)

    response = client.put(
        "/api/v1/settings/llm/credentials/zhipu",
        json={"model": "glm-4.6", "api_key": STORED_KEY},
    )

    assert response.status_code == 200
    body = response.json()
    assert "api_key" not in body
    assert body["key_hint"] == KEY_HINT
    assert body["model"] == "glm-4.6"
    call = save.await_args
    assert call.args == (USER["id"],)
    assert call.kwargs["provider"] == "zhipu"
    assert call.kwargs["api_key"] == STORED_KEY


def test_make_default_returns_masked_view(client, monkeypatch):
    monkeypatch.setattr(
        settings_llm, "set_default_provider", AsyncMock(return_value=_config()),
    )

    response = client.post("/api/v1/settings/llm/credentials/zhipu/default")

    assert response.status_code == 200
    body = response.json()
    assert "api_key" not in body
    assert body["is_default"] is True


def test_make_default_unknown_credential_is_404(client, monkeypatch):
    monkeypatch.setattr(
        settings_llm, "set_default_provider", AsyncMock(return_value=None),
    )

    response = client.post("/api/v1/settings/llm/credentials/zhipu/default")

    assert response.status_code == 404


def test_delete_credential(client, monkeypatch):
    delete = AsyncMock(return_value=True)
    monkeypatch.setattr(settings_llm, "delete_user_config", delete)

    response = client.delete("/api/v1/settings/llm/credentials/zhipu")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    delete.assert_awaited_once_with(USER["id"], "zhipu")


def test_delete_credential_unknown_is_404(client, monkeypatch):
    monkeypatch.setattr(
        settings_llm, "delete_user_config", AsyncMock(return_value=False),
    )

    response = client.delete("/api/v1/settings/llm/credentials/zhipu")

    assert response.status_code == 404


def test_legacy_get_settings_never_exposes_raw_key(client, monkeypatch):
    monkeypatch.setattr(
        settings_llm, "list_user_configs", AsyncMock(return_value=[_config()]),
    )

    response = client.get("/api/v1/settings/llm")

    assert response.status_code == 200
    body = response.json()
    assert "api_key" not in body
    assert body["configured"] is True
    assert body["source"] == "user"
    assert body["key_hint"] == KEY_HINT
    assert "api_key" not in body["credentials"][0]
    assert body["credentials"][0]["key_hint"] == KEY_HINT


def test_legacy_put_settings_saves_as_default_and_masks(client, monkeypatch):
    save = AsyncMock(return_value=_config())
    monkeypatch.setattr(settings_llm, "save_user_config", save)
    monkeypatch.setattr(
        settings_llm, "list_user_configs", AsyncMock(return_value=[_config()]),
    )

    response = client.put(
        "/api/v1/settings/llm",
        json={"provider": "zhipu", "model": "glm-4.7-flash", "api_key": STORED_KEY},
    )

    assert response.status_code == 200
    body = response.json()
    assert "api_key" not in body
    assert body["configured"] is True
    assert save.await_args.kwargs["is_default"] is True


def test_legacy_delete_settings_clears_all(client, monkeypatch):
    delete = AsyncMock(return_value=True)
    monkeypatch.setattr(settings_llm, "delete_user_config", delete)
    monkeypatch.setattr(settings_llm, "list_user_configs", AsyncMock(return_value=[]))

    response = client.delete("/api/v1/settings/llm")

    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is False
    assert body["source"] in {"server", "none"}
    delete.assert_awaited_once_with(USER["id"])


def test_connection_test_uses_stored_key_and_redacts_it(client, monkeypatch):
    monkeypatch.setattr(
        settings_llm, "get_user_config", AsyncMock(return_value=_config()),
    )
    seen: list[str] = []

    class FailingLLM:
        def __init__(self, api_key, base_url, model):
            seen.append(api_key)
            raise RuntimeError(f"provider rejected credential {api_key}")

    monkeypatch.setattr(settings_llm, "OpenAICompatibleLLM", FailingLLM)

    response = client.post(
        "/api/v1/settings/llm/test",
        json={"provider": "zhipu", "model": "glm-4.7-flash", "api_key": ""},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert seen == [STORED_KEY]
    assert STORED_KEY not in body["message"]
    assert "[REDACTED]" in body["message"]


def test_connection_test_rejects_unknown_provider_before_key_check(client, monkeypatch):
    get_config = AsyncMock(return_value=None)
    monkeypatch.setattr(settings_llm, "get_user_config", get_config)

    response = client.post(
        "/api/v1/settings/llm/test",
        json={"provider": "not-a-provider", "model": "x"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "不支持的模型服务商"
    get_config.assert_not_awaited()


def test_connection_test_allows_keyless_ollama_case_insensitive(client, monkeypatch):
    monkeypatch.setattr(settings_llm, "get_user_config", AsyncMock(return_value=None))
    seen: list[tuple[str, str]] = []

    class FakeLLM:
        def __init__(self, api_key, base_url, model):
            seen.append((api_key, base_url))

        async def astream(self, messages, max_tokens):
            yield "OK"

    monkeypatch.setattr(settings_llm, "OpenAICompatibleLLM", FakeLLM)

    response = client.post(
        "/api/v1/settings/llm/test",
        json={"provider": " OLLAMA ", "model": "qwen3-coder:30b"},
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert seen and seen[0][0] == ""

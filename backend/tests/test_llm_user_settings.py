"""BYOK: per-user keys are encrypted, masked, retained on edits and preferred."""
from unittest.mock import AsyncMock

import pytest

from app.api.v1.settings_llm import _public_view
from app.config import settings
from app.core.llm import factory, user_settings


class _FakeCredentialsDB:
    """In-memory stand-in for the ``user_llm_providers`` SQL shapes.

    Mirrors ``app.db.execute`` by returning rows only for ``RETURNING``
    statements; other writes return ``[]``. ``updated_at`` is a monotonically
    increasing counter so "most recently updated" ordering is deterministic.
    """

    def __init__(self) -> None:
        self.rows: dict[tuple[int, str], tuple] = {}
        self._clock = 0

    def _tick(self) -> int:
        self._clock += 1
        return self._clock

    async def query(self, sql: str, params):
        if "api_key_enc FROM user_llm_providers" in sql:
            row = self.rows.get((params[0], params[1]))
            return [(row[3],)] if row else []
        if "SELECT 1 FROM user_llm_providers" in sql:
            has_default = any(
                key[0] == params[0] and row[6] for key, row in self.rows.items()
            )
            return [("1",)] if has_default else []
        if "AND provider = %s" in sql:
            row = self.rows.get((params[0], params[1]))
            return [row] if row else []
        rows = [row for key, row in self.rows.items() if key[0] == params[0]]
        rows.sort(key=lambda row: (bool(row[6]), row[7]), reverse=True)
        return rows[:1] if "LIMIT 1" in sql else rows

    async def execute(self, sql: str, params):
        normalized = " ".join(sql.split())
        if normalized.startswith("INSERT INTO user_llm_providers"):
            user_id, provider, base_url, model, encrypted, context_window, effort = params
            existing = self.rows.get((user_id, provider))
            # ON CONFLICT DO UPDATE leaves is_default untouched.
            is_default = existing[6] if existing else False
            self.rows[(user_id, provider)] = (
                provider, base_url, model, encrypted,
                context_window, effort, is_default, self._tick(),
            )
            return []
        if "SET is_default = FALSE" in normalized:
            for key, row in list(self.rows.items()):
                if key[0] == params[0]:
                    self.rows[key] = row[:6] + (False, row[7])
            return []
        if "SET is_default = TRUE" in normalized:
            if "provider = (" in normalized:
                # delete_user_config promotion: most recently updated row.
                candidates = [key for key in self.rows if key[0] == params[0]]
                if candidates:
                    key = max(candidates, key=lambda item: self.rows[item][7])
                    self.rows[key] = self.rows[key][:6] + (True, self.rows[key][7])
                return []
            key = (params[0], params[1])
            if key in self.rows:
                self.rows[key] = self.rows[key][:6] + (True, self.rows[key][7])
            return []
        if normalized.startswith("DELETE FROM user_llm_providers"):
            if "RETURNING is_default" in normalized:
                row = self.rows.pop((params[0], params[1]), None)
                return [(row[6],)] if row else []
            deleted = [
                (key[0],) for key in list(self.rows) if key[0] == params[0]
            ]
            for key in list(self.rows):
                if key[0] == params[0]:
                    del self.rows[key]
            return deleted
        return []


@pytest.fixture
def credentials_db(monkeypatch):
    fake = _FakeCredentialsDB()
    monkeypatch.setattr(user_settings, "query", fake.query)
    monkeypatch.setattr(user_settings, "execute", fake.execute)
    return fake


def test_key_encryption_roundtrip_and_tamper_detection():
    token = user_settings.encrypt_key("sk-secret-value")
    assert token != "sk-secret-value"
    assert user_settings.decrypt_key(token) == "sk-secret-value"
    with pytest.raises(ValueError):
        user_settings.decrypt_key(token[:-4] + "AAAA")


def test_provider_alias_returns_spec():
    spec = user_settings.provider_by_id("zhipu")
    assert spec is not None
    assert spec.default_model == "glm-4.7-flash"
    assert user_settings.provider_by_id("longcat") is None


@pytest.mark.asyncio
async def test_save_keeps_existing_key_when_not_retyped(credentials_db):
    first = await user_settings.save_user_config(
        7, provider="dashscope", model="qwen3.8-max", api_key="sk-first-key"
    )
    assert first["api_key"] == "sk-first-key"
    assert first["key_hint"].endswith("key")
    assert first["is_default"] is True

    second = await user_settings.save_user_config(
        7, provider="dashscope", model="qwen3.5-plus", api_key=None
    )
    assert second["api_key"] == "sk-first-key"
    assert second["model"] == "qwen3.5-plus"
    assert second["is_default"] is True

    with pytest.raises(ValueError):
        await user_settings.save_user_config(7, provider="unknown", model="x", api_key="k")


@pytest.mark.asyncio
async def test_first_save_auto_defaults_when_user_has_no_default(credentials_db):
    saved = await user_settings.save_user_config(
        7, provider="zhipu", model="glm-4.7-flash", api_key="sk-zhipu-key"
    )

    assert saved["is_default"] is True
    stored = await user_settings.list_user_configs(7)
    assert [row["provider"] for row in stored] == ["zhipu"]
    assert stored[0]["is_default"] is True


@pytest.mark.asyncio
async def test_saving_second_provider_as_default_switches_default(credentials_db):
    await user_settings.save_user_config(
        7, provider="zhipu", model="glm-4.7-flash", api_key="sk-zhipu-key"
    )

    switched = await user_settings.save_user_config(
        7, provider="deepseek", model="deepseek-chat",
        api_key="sk-deepseek-key", is_default=True,
    )

    assert switched["is_default"] is True
    assert (await user_settings.get_user_config(7, "zhipu"))["is_default"] is False
    default = await user_settings.get_user_config(7)
    assert default["provider"] == "deepseek"
    assert default["is_default"] is True


@pytest.mark.asyncio
async def test_editing_non_default_credential_does_not_steal_default(credentials_db):
    await user_settings.save_user_config(
        7, provider="zhipu", model="glm-4.7-flash", api_key="sk-zhipu-key"
    )
    await user_settings.save_user_config(
        7, provider="deepseek", model="deepseek-chat", api_key="sk-deepseek-key"
    )

    edited = await user_settings.save_user_config(
        7, provider="deepseek", model="deepseek-reasoner"
    )

    assert edited["is_default"] is False
    assert (await user_settings.get_user_config(7, "zhipu"))["is_default"] is True
    assert (await user_settings.get_user_config(7))["provider"] == "zhipu"


@pytest.mark.asyncio
async def test_deleting_default_promotes_remaining_credential(credentials_db):
    await user_settings.save_user_config(
        7, provider="zhipu", model="glm-4.7-flash", api_key="sk-zhipu-key"
    )
    await user_settings.save_user_config(
        7, provider="deepseek", model="deepseek-chat", api_key="sk-deepseek-key"
    )

    assert await user_settings.delete_user_config(7, "zhipu") is True

    assert await user_settings.get_user_config(7, "zhipu") is None
    promoted = await user_settings.get_user_config(7, "deepseek")
    assert promoted["is_default"] is True
    assert (await user_settings.get_user_config(7))["provider"] == "deepseek"


@pytest.mark.asyncio
async def test_get_user_config_normalizes_provider_id(credentials_db):
    await user_settings.save_user_config(
        7, provider="zhipu", model="glm-4.7-flash", api_key="sk-zhipu-key"
    )

    for lookup in ("Zhipu", " ZHIPU "):
        found = await user_settings.get_user_config(7, lookup)
        assert found is not None
        assert found["provider"] == "zhipu"


def test_public_view_never_returns_the_raw_key():
    view = _public_view({
        "provider": "dashscope",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen3.8-max",
        "api_key": "sk-very-secret",
        "key_hint": "••••cret",
        "is_default": True,
        "context_window": None,
        "reasoning_effort": "",
        "updated_at": None,
    }, {"role": "demo", "is_guest": False})
    payload = view.model_dump()
    assert "api_key" not in payload
    assert payload["configured"] is True
    assert payload["source"] == "user"
    assert payload["key_hint"] == "••••cret"


@pytest.mark.asyncio
async def test_factory_prefers_user_config_and_uses_session_model(monkeypatch):
    monkeypatch.setattr(factory, "get_user_config", AsyncMock(return_value={
        "provider": "deepseek",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "api_key": "sk-user",
        "key_hint": "••••user",
    }))

    llm = await factory.get_llm(7, model="deepseek-reasoner")

    assert isinstance(llm, factory.OpenAICompatibleLLM)
    assert llm.model == "deepseek-reasoner"
    assert str(llm.client.base_url).rstrip("/") == "https://api.deepseek.com/v1"


@pytest.mark.asyncio
async def test_server_fallback_can_be_disabled_for_deployments(monkeypatch):
    monkeypatch.setattr(factory, "get_user_config", AsyncMock(return_value=None))
    monkeypatch.setattr(settings, "llm_allow_server_fallback", False)
    monkeypatch.setattr(settings, "dashscope_api_key", "sk-server")

    with pytest.raises(RuntimeError, match="个人 API Key"):
        await factory.get_llm(7)


@pytest.mark.asyncio
async def test_server_chain_still_works_when_fallback_allowed(monkeypatch):
    monkeypatch.setattr(factory, "get_user_config", AsyncMock(return_value=None))
    monkeypatch.setattr(factory, "_fallback_allowed_for", AsyncMock(return_value=True))
    monkeypatch.setattr(settings, "llm_allow_server_fallback", True)
    monkeypatch.setattr(settings, "llm_model_priority", "dashscope")
    monkeypatch.setattr(settings, "dashscope_api_key", "sk-server")

    llm = await factory.get_llm(7)

    assert isinstance(llm, factory.FallbackLLM)
    assert llm.context_window == settings.default_context_window
    assert factory.server_default_model() == settings.dashscope_model


@pytest.mark.asyncio
async def test_server_key_reserved_for_guests_and_admins(monkeypatch):
    """注册用户默认不能用共享 Key；游客与管理员可以。"""
    async def fake_query(_sql, params):
        role, is_guest = fake_query.tier
        return [(role, is_guest)]

    monkeypatch.setattr("app.db.query", fake_query)
    monkeypatch.setattr(settings, "llm_allow_server_fallback", True)

    fake_query.tier = ("demo", False)
    assert await factory._fallback_allowed_for(7) is False

    fake_query.tier = ("demo", True)
    assert await factory._fallback_allowed_for(8) is True

    fake_query.tier = ("admin", False)
    assert await factory._fallback_allowed_for(1) is True

    monkeypatch.setattr(settings, "llm_server_fallback_registered", True)
    fake_query.tier = ("demo", False)
    assert await factory._fallback_allowed_for(7) is True


@pytest.mark.asyncio
async def test_registered_user_without_key_gets_byok_guidance(monkeypatch):
    monkeypatch.setattr(factory, "get_user_config", AsyncMock(return_value=None))
    monkeypatch.setattr(factory, "_fallback_allowed_for", AsyncMock(return_value=False))

    with pytest.raises(RuntimeError, match="个人 API Key"):
        await factory.get_llm(7)


@pytest.mark.asyncio
async def test_fallback_denied_when_db_lookup_fails(monkeypatch):
    """DB 异常时按拒绝处理，防止额度被意外消耗。"""
    async def broken_query(_sql, params):
        raise RuntimeError("db down")

    monkeypatch.setattr("app.db.query", broken_query)
    monkeypatch.setattr(settings, "llm_allow_server_fallback", True)
    assert await factory._fallback_allowed_for(7) is False
    assert await factory._fallback_allowed_for(None) is True  # 系统调用不受限

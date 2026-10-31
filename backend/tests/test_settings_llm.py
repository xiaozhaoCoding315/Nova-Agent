from app.models.schemas import LlmCredentialUpdate, LlmOverrides, LlmProviderOut


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
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        LlmOverrides(temperature=3)
    with pytest.raises(ValidationError):
        LlmOverrides(context_window=100)
    assert LlmOverrides(provider="zhipu", reasoning_effort="high").provider == "zhipu"

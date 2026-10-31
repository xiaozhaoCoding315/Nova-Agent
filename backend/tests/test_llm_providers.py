import pytest

from app.core.llm.providers import (
    PROVIDERS, get_provider, provider_list, resolve_base_url,
)


def test_catalog_ids_are_unique_and_longcat_is_gone():
    ids = [item.id for item in PROVIDERS]
    assert len(ids) == len(set(ids))
    assert "longcat" not in ids
    assert {"zhipu", "dashscope", "deepseek", "openai", "anthropic", "custom", "ollama"} <= set(ids)


def test_zhipu_is_the_free_default():
    zhipu = get_provider("zhipu")
    assert zhipu is not None
    assert zhipu.default_model == "glm-4.7-flash"
    assert zhipu.base_url == "https://open.bigmodel.cn/api/paas/v4"
    assert zhipu.free_tier is True
    assert zhipu.supports_reasoning is True


def test_locked_base_url_ignores_client_value():
    deepseek = get_provider("deepseek")
    assert resolve_base_url(deepseek, "https://evil.example/v1") == "https://api.deepseek.com/v1"


def test_custom_base_url_must_be_http_and_blocks_metadata():
    custom = get_provider("custom")
    with pytest.raises(ValueError):
        resolve_base_url(custom, "ftp://example.com")
    with pytest.raises(ValueError):
        resolve_base_url(custom, "http://169.254.169.254/v1")
    assert resolve_base_url(custom, "https://api.example.com/v1/") == "https://api.example.com/v1"


def test_public_payload_has_ui_metadata():
    item = next(row for row in provider_list() if row["id"] == "zhipu")
    assert item["icon"] == "zhipu"
    assert item["group"] == "domestic"
    assert item["base_url_locked"] is True
    assert item["models"][0] == "glm-4.7-flash"

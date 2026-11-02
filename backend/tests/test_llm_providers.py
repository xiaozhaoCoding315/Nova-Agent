import pytest

from app.core.llm.factory import OpenAICompatibleLLM
from app.core.llm.providers import (
    PROVIDERS, get_provider, provider_list, resolve_base_url,
)


def test_catalog_ids_are_unique_and_longcat_is_gone():
    ids = [item.id for item in PROVIDERS]
    assert len(PROVIDERS) == 16
    assert len(ids) == len(set(ids))
    assert "longcat" not in ids
    assert {"zhipu", "dashscope", "deepseek", "openai", "anthropic", "custom", "ollama"} <= set(ids)


def test_only_custom_and_ollama_have_unlocked_base_urls():
    unlocked = {item.id for item in PROVIDERS if not item.base_url_locked}
    assert unlocked == {"custom", "ollama"}


def test_anthropic_rejects_temperature_in_catalog():
    anthropic = get_provider("anthropic")
    assert anthropic.supports_temperature is False
    assert get_provider("zhipu").supports_temperature is True


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


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254./v1",             # trailing-dot IPv4
        "http://[::ffff:169.254.169.254]/v1",     # IPv4-mapped IPv6
        "http://[::ffff:a9fe:a9fe]/v1",           # same address in hex form
        "http://0.0.0.0/v1",                      # unspecified IPv4
        "http://[::]/v1",                         # unspecified IPv6
        "http://[fe80::1]/v1",                    # IPv6 link-local
        "http://metadata.google.internal./v1",    # trailing-dot metadata name
    ],
)
def test_blocked_host_variants_are_rejected(url):
    custom = get_provider("custom")
    with pytest.raises(ValueError):
        resolve_base_url(custom, url)


def test_ollama_loopback_is_still_allowed():
    ollama = get_provider("ollama")
    assert resolve_base_url(ollama, "http://127.0.0.1:11434/v1") == "http://127.0.0.1:11434/v1"
    assert resolve_base_url(ollama, "http://[::1]:11434/v1") == "http://[::1]:11434/v1"


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8000/v1",
        "http://127.8.9.10/v1",
        "http://[::1]:8000/v1",
    ],
)
def test_custom_loopback_is_rejected(url):
    custom = get_provider("custom")
    with pytest.raises(ValueError, match="不允许使用该地址"):
        resolve_base_url(custom, url)


@pytest.mark.parametrize("provider_id", ["custom", "ollama"])
def test_cgnat_metadata_is_rejected_for_every_provider(provider_id):
    spec = get_provider(provider_id)
    with pytest.raises(ValueError, match="不允许使用该地址"):
        resolve_base_url(spec, "http://100.100.100.200/v1")


@pytest.mark.parametrize(
    ("provider_id", "url"),
    [
        ("custom", "http://192.168.1.10:8000/v1"),
        ("ollama", "http://192.168.1.10:11434/v1"),
    ],
)
def test_lan_private_ranges_are_allowed_for_local_first_use(provider_id, url):
    spec = get_provider(provider_id)
    assert resolve_base_url(spec, url) == url


def test_openai_compatible_client_never_follows_redirects():
    llm = OpenAICompatibleLLM("key", "https://api.example.com/v1", "model")

    # httpx exposes the flag on the inner AsyncClient; the OpenAI SDK wrapper
    # does not re-export it, so _client is the only observable location.
    assert llm.client._client.follow_redirects is False


def test_public_payload_has_ui_metadata():
    item = next(row for row in provider_list() if row["id"] == "zhipu")
    assert item["icon"] == "zhipu"
    assert item["group"] == "domestic"
    assert item["base_url_locked"] is True
    assert item["models"][0] == "glm-4.7-flash"


def test_public_payload_and_resolver_share_normalized_url():
    gemini = get_provider("gemini")
    public_url = next(row for row in provider_list() if row["id"] == "gemini")["base_url"]
    assert public_url == "https://generativelanguage.googleapis.com/v1beta/openai"
    assert resolve_base_url(gemini, None) == public_url


def test_vision_capable_providers():
    vision = {item.id for item in PROVIDERS if item.supports_vision}
    assert vision == {
        "anthropic", "openai", "gemini", "openrouter", "ollama", "custom",
    }


def test_provider_public_exposes_vision_capability():
    payload = {item["id"]: item for item in provider_list()}
    assert payload["openai"]["supports_vision"] is True
    assert payload["deepseek"]["supports_vision"] is False

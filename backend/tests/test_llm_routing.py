"""Model routing by purpose: plan vs utility on the shared server key."""
import pytest

from app.config import settings
from app.core.llm import factory as factory_mod
from app.core.llm.factory import OpenAICompatibleLLM, _server_llm, get_llm, route_model_for


@pytest.fixture(autouse=True)
def providers(monkeypatch):
    monkeypatch.setattr(settings, "llm_model_priority", "dashscope")
    monkeypatch.setattr(settings, "dashscope_api_key", "sk-test")
    monkeypatch.setattr(settings, "dashscope_model", "qwen3.8-max")
    monkeypatch.setattr(settings, "deepseek_api_key", "")
    monkeypatch.setattr(settings, "longcat_api_key", "")
    monkeypatch.setattr(settings, "llm_route_plan", "qwen3.8-max")
    monkeypatch.setattr(settings, "llm_route_utility", "qwen-turbo")


def test_route_model_for_purposes():
    assert route_model_for("plan") == "qwen3.8-max"
    assert route_model_for("utility") == "qwen-turbo"
    assert route_model_for(None) is None
    assert route_model_for("chat") is None


def test_server_llm_override_uses_single_provider():
    llm = _server_llm(model_override="qwen-turbo")
    assert isinstance(llm, OpenAICompatibleLLM)
    assert llm.model == "qwen-turbo"


def test_server_llm_without_override_keeps_fallback_chain():
    from app.core.llm.fallback import FallbackLLM
    monkey = pytest.MonkeyPatch()
    monkey.setattr(settings, "deepseek_api_key", "sk-ds")
    try:
        llm = _server_llm()
        assert isinstance(llm, FallbackLLM)
    finally:
        monkey.undo()


@pytest.mark.asyncio
async def test_get_llm_routes_utility_on_server_key():
    llm = await get_llm(user_id=None, purpose="utility")
    assert isinstance(llm, OpenAICompatibleLLM)
    assert llm.model == "qwen-turbo"


@pytest.mark.asyncio
async def test_byok_model_is_never_routed(monkeypatch):
    async def fake_config(user_id):
        return {"api_key": "sk-personal", "base_url": "https://example.com/v1",
                "model": "my-model"}

    monkeypatch.setattr(factory_mod, "get_user_config", fake_config)
    llm = await get_llm(user_id=7, purpose="utility")
    assert isinstance(llm, OpenAICompatibleLLM)
    assert llm.model == "my-model"


@pytest.mark.asyncio
async def test_llm_json_passes_purpose(monkeypatch):
    from app.core.llm import json_call

    seen = {}

    class FakeLLM:
        model = "routed"

        async def astream_with_tools(self, messages, tools, **kwargs):
            seen["llm"] = self
            yield {"type": "content", "content": '{"ok": 1}'}
            yield {"type": "usage", "usage": {"prompt_tokens": 1, "completion_tokens": 1}}
            yield {"type": "finish", "finish_reason": "stop"}

    async def fake_get_llm(user_id=None, model=None, purpose=None):
        seen["purpose"] = purpose
        return FakeLLM()

    recorded = []

    async def fake_record(*args, **kwargs):
        recorded.append(kwargs.get("source"))

    monkeypatch.setattr(json_call, "get_llm", fake_get_llm)
    monkeypatch.setattr(json_call, "record_usage", fake_record)
    data = await json_call.llm_json("prompt", source="memory", purpose="utility")
    assert data == {"ok": 1}
    assert seen["purpose"] == "utility"
    assert recorded == ["memory"]

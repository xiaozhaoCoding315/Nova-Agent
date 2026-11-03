"""Live tasks exist and provider construction never leaks keys."""
import asyncio

import pytest

from app.config import settings
from app.core.llm.anthropic import AnthropicLLM
from app.core.llm.factory import OpenAICompatibleLLM
from evals.executors import EvalConfigError, build_live_llm
from evals.tasks import tasks_for_mode

LIVE_IDS = {"live_read_locate", "live_fix_bug", "live_add_test"}


def test_live_tasks_are_registered():
    assert {task.id for task in tasks_for_mode("live")} == LIVE_IDS
    for task in tasks_for_mode("live"):
        assert task.script is None
        assert task.timeout_s >= 180


def test_build_live_llm_requires_a_key(monkeypatch):
    monkeypatch.setattr(settings, "zhipu_api_key", "")
    with pytest.raises(EvalConfigError, match="zhipu"):
        build_live_llm("zhipu")


def test_build_live_llm_uses_configured_provider(monkeypatch):
    monkeypatch.setattr(settings, "zhipu_api_key", "test-key-not-real")
    monkeypatch.setattr(settings, "zhipu_model", "glm-test")
    config = build_live_llm("zhipu")
    try:
        assert config.provider == "zhipu"
        assert config.model == "glm-test"
        assert isinstance(config.llm, OpenAICompatibleLLM)
        assert config.llm.model == "glm-test"
    finally:
        asyncio.run(config.llm.client.close())


def test_build_live_llm_builds_anthropic(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key-not-real")
    monkeypatch.setattr(settings, "anthropic_model", "claude-test")
    config = build_live_llm("anthropic")
    assert config.provider == "anthropic"
    assert config.model == "claude-test"
    assert isinstance(config.llm, AnthropicLLM)


def test_auto_picks_first_configured_provider(monkeypatch):
    monkeypatch.setattr(settings, "zhipu_api_key", "")
    monkeypatch.setattr(settings, "deepseek_api_key", "test-key-not-real")
    monkeypatch.setattr(settings, "llm_model_priority", "zhipu,deepseek")
    config = build_live_llm("auto")
    try:
        assert config.provider == "deepseek"
        assert isinstance(config.llm, OpenAICompatibleLLM)
    finally:
        asyncio.run(config.llm.client.close())

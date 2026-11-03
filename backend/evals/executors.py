"""LLM executors for scripted and live eval modes."""
from __future__ import annotations

import copy
import inspect
from dataclasses import dataclass
from typing import Any, AsyncIterator

from app.config import settings
from app.core.llm.anthropic import AnthropicLLM
from app.core.llm.factory import OpenAICompatibleLLM


class ScriptExhausted(RuntimeError):
    """The agent asked for more LLM rounds than the script provides."""


class EvalConfigError(RuntimeError):
    """Live eval cannot start because provider configuration is missing."""


class ScriptedExecutor:
    supports_vision: bool
    context_window: int

    def __init__(
        self,
        rounds,
        *,
        context_window: int = 131_072,
        supports_vision: bool = False,
    ):
        self._rounds = list(rounds)
        self.supports_vision = supports_vision
        self.context_window = context_window
        self.llm_messages: list[list[dict[str, Any]]] = []

    async def astream_with_tools(
        self, messages: list[dict], tools: list[dict]
    ) -> AsyncIterator[dict]:
        self.llm_messages.append(copy.deepcopy(messages))
        if not self._rounds:
            raise ScriptExhausted(
                f"ScriptExhausted: LLM 调用次数超过脚本轮次（已调用 {len(self.llm_messages)} 次）"
            )
        for event in self._rounds.pop(0):
            yield event


class LiveExecutor:
    def __init__(self, llm):
        self._llm = llm
        self.llm_messages: list[list[dict[str, Any]]] = []

    def __getattr__(self, name: str):
        return getattr(self._llm, name)

    async def astream_with_tools(
        self, messages: list[dict], tools: list[dict]
    ) -> AsyncIterator[dict]:
        snapshot = copy.deepcopy(messages)
        self.llm_messages.append(snapshot)
        async for event in self._llm.astream_with_tools(snapshot, tools):
            yield event


@dataclass(frozen=True)
class LiveConfig:
    llm: Any
    provider: str
    model: str


def _api_key(provider: str) -> str:
    return {
        "zhipu": settings.zhipu_api_key,
        "deepseek": settings.deepseek_api_key,
        "dashscope": settings.dashscope_api_key,
        "anthropic": settings.anthropic_api_key,
    }.get(provider, "")


def _configured_providers() -> list[str]:
    names = []
    for raw in settings.llm_priority_list:
        name = raw.strip().lower()
        if name in ("zhipu", "deepseek", "dashscope", "anthropic") and _api_key(name):
            if name not in names:
                names.append(name)
    return names


def build_live_llm(provider: str = "auto", model: str | None = None) -> LiveConfig:
    requested = (provider or "auto").strip().lower()
    if requested == "auto":
        available = _configured_providers()
        if not available:
            raise EvalConfigError(
                "未配置任何 live eval provider API Key；"
                "请在 backend/.env 配置 zhipu/deepseek/dashscope/anthropic 之一"
            )
        requested = available[0]

    if requested not in ("zhipu", "deepseek", "dashscope", "anthropic"):
        raise EvalConfigError(f"未知 provider：{requested}")

    key = _api_key(requested)
    if not key:
        raise EvalConfigError(f"未配置 {requested} API Key，跳过 live eval")

    if requested == "anthropic":
        chosen = (model or settings.anthropic_model).strip()
        llm = AnthropicLLM(key, settings.anthropic_base_url, chosen)
        return LiveConfig(llm=llm, provider=requested, model=chosen)

    base_url, default_model = {
        "zhipu": (settings.zhipu_base_url, settings.zhipu_model),
        "deepseek": ("https://api.deepseek.com/v1", "deepseek-chat"),
        "dashscope": (settings.dashscope_base_url, settings.dashscope_model),
    }[requested]
    chosen = (model or default_model).strip()
    llm = OpenAICompatibleLLM(key, base_url, chosen)
    return LiveConfig(llm=llm, provider=requested, model=chosen)


async def close_live_llm(llm) -> None:
    client = getattr(llm, "client", None)
    close = getattr(client, "close", None)
    if not callable(close):
        return
    result = close()
    if inspect.isawaitable(result):
        await result

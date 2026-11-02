import httpx
import structlog
from openai import AsyncOpenAI

from app.config import settings
from app.core.agent.image_input import strip_image_blocks
from app.core.llm.anthropic import AnthropicLLM
from app.core.llm.base import LLMProvider
from app.core.llm.fallback import FallbackLLM
from app.core.llm.providers import get_provider
from app.core.llm.user_settings import get_user_config

logger = structlog.get_logger()

NOT_CONFIGURED_MESSAGE = (
    "尚未配置可用模型：请在「设置 → 模型与密钥」填写个人 API Key"
)


class LLMNotConfiguredError(RuntimeError):
    """No usable model configuration — retrying the same call cannot help."""


class OpenAICompatibleLLM(LLMProvider):
    supports_tools = True

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        reasoning_effort: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        context_window: int | None = None,
        supports_vision: bool = False,
    ):
        self.client = AsyncOpenAI(
            api_key=api_key or "ollama",
            base_url=base_url,
            http_client=httpx.AsyncClient(follow_redirects=False),
        )
        self.model = model
        self.reasoning_effort = (reasoning_effort or "").strip().lower() or None
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.context_window = context_window
        self.supports_vision = supports_vision

    def _extras(self) -> dict:
        extras: dict = {}
        if self.reasoning_effort:
            extras["reasoning_effort"] = self.reasoning_effort
        if self.temperature is not None:
            extras["temperature"] = self.temperature
        if self.max_tokens:
            extras["max_tokens"] = self.max_tokens
        return extras

    def _prepare_messages(self, messages: list[dict]) -> list[dict]:
        return messages if self.supports_vision else strip_image_blocks(messages)

    async def astream(self, messages: list[dict], **kwargs):
        messages = self._prepare_messages(messages)
        # kwargs win over stored extras so a caller-supplied max_tokens is not
        # passed twice (Python rejects duplicate keyword arguments).
        attempts: list[dict] = []
        for attempt in ({**self._extras(), **kwargs}, dict(kwargs)):
            if not attempts or attempt != attempts[-1]:
                attempts.append(attempt)
        for index, attempt in enumerate(attempts):
            try:
                stream = await self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    stream=True,
                    **attempt,
                )
                break
            except Exception:  # noqa: BLE001 — provider may reject optional params
                if index + 1 >= len(attempts):
                    raise
                logger.warning(
                    "llm_retry_reduced_params",
                    dropped=sorted(set(attempt) - set(attempts[index + 1])),
                )
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    async def astream_with_tools(self, messages: list[dict], tools: list[dict], **kwargs):
        """Streamed OpenAI-compatible function calling.

        tool_calls deltas arrive fragmented across chunks; we accumulate them
        by index and emit one aggregated event before finish. Real token usage
        is requested via stream_options; providers that reject optional
        parameters are retried with fewer extras, then bare.
        """
        messages = self._prepare_messages(messages)

        async def _create(**extra):
            return await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                stream=True,
                **extra,
            )

        extras = {**self._extras(), **kwargs}
        ladder: list[dict] = [
            {"stream_options": {"include_usage": True}, **extras},
            dict(extras),
        ]
        if "temperature" in extras:
            ladder.append({
                key: value for key, value in extras.items() if key != "temperature"
            })
        ladder.append(dict(kwargs))
        ladder.append({})

        # Never send two byte-identical requests: dedupe the fallback ladder.
        attempts: list[dict] = []
        for attempt in ladder:
            if attempt not in attempts:
                attempts.append(attempt)

        for index, attempt in enumerate(attempts):
            try:
                stream = await _create(**attempt)
                break
            except Exception:  # noqa: BLE001
                if index + 1 >= len(attempts):
                    raise
                logger.warning(
                    "llm_tool_retry_dropped_params",
                    dropped=sorted(set(attempt) - set(attempts[index + 1])),
                )

        acc: dict[int, dict] = {}
        finish_reason = "stop"
        usage: dict | None = None
        async for chunk in stream:
            chunk_usage = getattr(chunk, "usage", None)
            if chunk_usage:
                usage = {
                    "prompt_tokens": chunk_usage.prompt_tokens,
                    "completion_tokens": chunk_usage.completion_tokens,
                    "model": self.model,
                }
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            delta = choice.delta
            if delta and delta.content:
                yield {"type": "content", "content": delta.content}
            if delta and delta.tool_calls:
                for tc in delta.tool_calls:
                    slot = acc.setdefault(tc.index, {"id": "", "name": "", "arguments": ""})
                    if tc.id:
                        slot["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            slot["name"] = tc.function.name
                        if tc.function.arguments:
                            slot["arguments"] += tc.function.arguments
            if choice.finish_reason:
                finish_reason = choice.finish_reason

        if acc:
            ordered = [acc[i] for i in sorted(acc)]
            yield {"type": "tool_calls", "tool_calls": ordered}
        if usage:
            yield {"type": "usage", "usage": usage}
        yield {"type": "finish", "finish_reason": finish_reason}


def server_default_model() -> str | None:
    """Model the shared server key would use, for display and fallbacks."""
    for name in settings.llm_priority_list:
        name = name.lower()
        if name == "zhipu" and settings.zhipu_api_key:
            return settings.zhipu_model
        if name == "deepseek" and settings.deepseek_api_key:
            return "deepseek-chat"
        if name == "dashscope" and settings.dashscope_api_key:
            return settings.dashscope_model
        if name == "anthropic" and settings.anthropic_api_key:
            return settings.anthropic_model
    return None


def _server_llm(model_override: str | None = None) -> LLMProvider:
    """Build the shared server-key chain.

    With ``model_override`` (purpose routing) the first provider that has a
    key is used directly with that model name — routed models are provider
    specific, so cross-provider fallback does not apply.
    """
    providers = []
    for name in settings.llm_priority_list:
        name = name.lower()
        if name == "zhipu" and settings.zhipu_api_key:
            if model_override:
                return OpenAICompatibleLLM(
                    settings.zhipu_api_key, settings.zhipu_base_url, model_override)
            providers.append(OpenAICompatibleLLM(
                settings.zhipu_api_key, settings.zhipu_base_url, settings.zhipu_model))
        elif name == "deepseek" and settings.deepseek_api_key:
            if model_override:
                return OpenAICompatibleLLM(
                    settings.deepseek_api_key,
                    "https://api.deepseek.com/v1", model_override)
            providers.append(OpenAICompatibleLLM(
                settings.deepseek_api_key,
                "https://api.deepseek.com/v1",
                "deepseek-chat"))
        elif name == "dashscope" and settings.dashscope_api_key:
            if model_override:
                return OpenAICompatibleLLM(
                    settings.dashscope_api_key,
                    settings.dashscope_base_url, model_override)
            providers.append(OpenAICompatibleLLM(
                settings.dashscope_api_key,
                settings.dashscope_base_url,
                settings.dashscope_model))
        elif name == "anthropic" and settings.anthropic_api_key:
            providers.append(AnthropicLLM(
                settings.anthropic_api_key,
                settings.anthropic_base_url,
                model_override or settings.anthropic_model,
            ))

    if not providers:
        raise LLMNotConfiguredError(NOT_CONFIGURED_MESSAGE)
    return FallbackLLM(providers)


def route_model_for(purpose: str | None) -> str | None:
    """Configured model override for a purpose, if any."""
    if purpose == "plan":
        return settings.llm_route_plan or None
    if purpose == "utility":
        return settings.llm_route_utility or None
    return None


def resolve_context_window(
    user_id: int | None,
    provider: LLMProvider | None = None,
    overrides: dict | None = None,
) -> int:
    """Effective context window for the context meter (tokens)."""
    if overrides and overrides.get("context_window"):
        return int(overrides["context_window"])
    if provider is not None and getattr(provider, "context_window", None):
        return int(provider.context_window)
    return settings.default_context_window


async def _fallback_allowed_for(user_id: int | None) -> bool:
    """服务端共享 Key 只供应给：系统调用（无用户）、游客、管理员；
    注册用户默认必须自带 Key（保护部署者额度）。DB 异常时按拒绝处理。"""
    if user_id is None:
        return True
    if not settings.llm_allow_server_fallback:
        return False
    try:
        from app.db import query
        rows = await query(
            "SELECT role, is_guest FROM users WHERE id = %s", (user_id,)
        )
    except Exception:  # noqa: BLE001
        return False
    if not rows:
        return False
    role, is_guest = rows[0][0], bool(rows[0][1])
    return is_guest or role == "admin" or settings.llm_server_fallback_registered


async def get_llm(
    user_id: int | None = None,
    model: str | None = None,
    purpose: str | None = None,
    overrides: dict | None = None,
) -> LLMProvider:
    """Resolve the provider for one call.

    A session-level provider/model override wins over the saved default, but
    only when that provider has a saved credential. A missing credential is an
    explicit error instead of a silent fallback to another vendor.
    """
    overrides = overrides or {}
    requested_provider = (overrides.get("provider") or "").strip().lower() or None

    if user_id is not None:
        config = await get_user_config(user_id, requested_provider)
        if requested_provider and not config:
            raise LLMNotConfiguredError("请先在设置里配置该厂商的 API Key")
        if config:
            if not config["api_key"] and config["provider"] != "ollama":
                raise LLMNotConfiguredError(
                    config.get("key_error") or "个人模型 API Key 无效，请重新保存"
                )
            chosen_model = (overrides.get("model") or model or config["model"]).strip()
            effort = overrides.get("reasoning_effort", None)
            if effort is None:
                effort = config.get("reasoning_effort")
            effort = (effort or "").strip().lower() or None
            # Reasoning effort is a chat-turn setting: summaries and fact
            # extraction (purpose != None) must stay cheap and fast.
            if purpose:
                effort = None
            spec = get_provider(config["provider"])
            context = (
                overrides.get("context_window")
                or config.get("context_window")
                or (spec.context_window if spec else settings.default_context_window)
            )
            temperature = overrides.get("temperature")
            max_tokens = overrides.get("max_tokens")
            if spec and spec.kind == "anthropic":
                llm = AnthropicLLM(
                    config["api_key"], config["base_url"], chosen_model,
                    max_tokens=max_tokens, reasoning_effort=effort,
                )
            else:
                llm = OpenAICompatibleLLM(
                    config["api_key"], config["base_url"], chosen_model,
                    reasoning_effort=effort, temperature=temperature,
                    max_tokens=max_tokens, context_window=int(context),
                    supports_vision=bool(spec and spec.supports_vision),
                )
            llm.context_window = int(context)
            return llm

    if requested_provider:
        raise LLMNotConfiguredError("请先在设置里配置该厂商的 API Key")

    if not await _fallback_allowed_for(user_id):
        raise LLMNotConfiguredError(
            "请先在「设置 → 模型」配置你的个人 API Key，再开始对话"
            if user_id is not None
            else "尚未配置个人模型 API Key，且服务端未开放共享模型"
        )
    llm = _server_llm(model_override=route_model_for(purpose))
    llm.context_window = settings.default_context_window
    return llm

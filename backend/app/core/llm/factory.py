from openai import AsyncOpenAI
from app.config import settings
from app.core.llm.base import LLMProvider
from app.core.llm.fallback import FallbackLLM
from app.core.llm.user_settings import get_user_config


class OpenAICompatibleLLM(LLMProvider):
    def __init__(self, api_key: str, base_url: str, model: str, reasoning_effort: str | None = None):
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        # 推理强度只在对话主链路携带；摘要/抽取等工具型调用不带。
        self.reasoning_effort = (reasoning_effort or "").strip().lower() or None
        # 上下文窗口（token）：BYOK 用户可配；由 get_llm 统一填默认值。
        self.context_window: int | None = None

    async def astream(self, messages: list[dict], **kwargs):
        stream = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            stream=True,
            **kwargs,
        )
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    async def astream_with_tools(self, messages: list[dict], tools: list[dict], **kwargs):
        """Streamed OpenAI-compatible function calling.

        tool_calls deltas arrive fragmented across chunks; we accumulate them
        by index and emit one aggregated event before finish, keeping the
        downstream chat loop simple. Real token usage is requested via
        stream_options (providers that reject it are retried without).
        """
        async def _create(**extra):
            return await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                stream=True,
                **extra,
            )

        try:
            stream = await _create(stream_options={"include_usage": True}, **kwargs)
        except Exception:  # noqa: BLE001 — provider may not support include_usage
            try:
                stream = await _create(**kwargs)
            except Exception:  # noqa: BLE001 — provider may reject reasoning_effort etc.
                if kwargs:
                    stream = await _create()
                else:
                    raise

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
        if name == "longcat" and settings.longcat_api_key:
            return settings.longcat_model
        if name == "deepseek" and settings.deepseek_api_key:
            return "deepseek-chat"
        if name == "dashscope" and settings.dashscope_api_key:
            return settings.dashscope_model
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
        if name == "longcat" and settings.longcat_api_key:
            if model_override:
                return OpenAICompatibleLLM(
                    settings.longcat_api_key, settings.longcat_base_url, model_override)
            providers.append(OpenAICompatibleLLM(
                settings.longcat_api_key, settings.longcat_base_url, settings.longcat_model))
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

    if not providers:
        raise RuntimeError("No LLM providers configured")
    return FallbackLLM(providers)


def route_model_for(purpose: str | None) -> str | None:
    """Configured model override for a purpose, if any."""
    if purpose == "plan":
        return settings.llm_route_plan or None
    if purpose == "utility":
        return settings.llm_route_utility or None
    return None


def resolve_context_window(user_id: int | None, provider: LLMProvider | None = None) -> int:
    """Effective context window for the context meter (tokens)."""
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
) -> LLMProvider:
    """Resolve the provider for one call.

    A user-saved key takes precedence and is used exclusively, so a bad personal
    config never silently spends the server owner's quota — and purpose routing
    never overrides a BYOK user's own model choice. Without a personal key, the
    shared env-key chain only serves guests and admins (system calls too);
    registered users must bring their own key unless the deployment explicitly
    opens ``llm_server_fallback_registered``.
    """
    if user_id is not None:
        config = await get_user_config(user_id)
        if config:
            if not config["api_key"]:
                raise RuntimeError(config.get("key_error") or "个人模型 API Key 无效，请重新保存")
            chosen_model = (model or config["model"]).strip()
            llm = OpenAICompatibleLLM(
                config["api_key"], config["base_url"], chosen_model,
                reasoning_effort=config.get("reasoning_effort"),
            )
            llm.context_window = config.get("context_window") or settings.default_context_window
            return llm

    if not await _fallback_allowed_for(user_id):
        raise RuntimeError(
            "请先在「设置 → 模型」配置你的个人 API Key，再开始对话"
            if user_id is not None
            else "尚未配置个人模型 API Key，且服务端未开放共享模型"
        )
    llm = _server_llm(model_override=route_model_for(purpose))
    llm.context_window = settings.default_context_window
    return llm

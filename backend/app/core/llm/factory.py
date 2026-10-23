from openai import AsyncOpenAI
from app.config import settings
from app.core.llm.base import LLMProvider
from app.core.llm.fallback import FallbackLLM
from app.core.llm.user_settings import get_user_config


class OpenAICompatibleLLM(LLMProvider):
    def __init__(self, api_key: str, base_url: str, model: str):
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.model = model

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
            stream = await _create(**kwargs)

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


def _server_llm() -> LLMProvider:
    providers = []
    for name in settings.llm_priority_list:
        name = name.lower()
        if name == "longcat" and settings.longcat_api_key:
            providers.append(OpenAICompatibleLLM(
                settings.longcat_api_key, settings.longcat_base_url, settings.longcat_model))
        elif name == "deepseek" and settings.deepseek_api_key:
            providers.append(OpenAICompatibleLLM(
                settings.deepseek_api_key,
                "https://api.deepseek.com/v1",
                "deepseek-chat"))
        elif name == "dashscope" and settings.dashscope_api_key:
            providers.append(OpenAICompatibleLLM(
                settings.dashscope_api_key,
                settings.dashscope_base_url,
                settings.dashscope_model))

    if not providers:
        raise RuntimeError("No LLM providers configured")
    return FallbackLLM(providers)


async def get_llm(user_id: int | None = None, model: str | None = None) -> LLMProvider:
    """Resolve the provider for one call.

    A user-saved key takes precedence and is used exclusively, so a bad personal
    config never silently spends the server owner's quota. Without one, the
    shared env-key chain is used unless the deployment disables that fallback.
    """
    if user_id is not None:
        config = await get_user_config(user_id)
        if config:
            if not config["api_key"]:
                raise RuntimeError(config.get("key_error") or "个人模型 API Key 无效，请重新保存")
            chosen_model = (model or config["model"]).strip()
            return OpenAICompatibleLLM(config["api_key"], config["base_url"], chosen_model)

    if not settings.llm_allow_server_fallback:
        raise RuntimeError("尚未配置个人模型 API Key，且服务端未开放共享模型")
    return _server_llm()

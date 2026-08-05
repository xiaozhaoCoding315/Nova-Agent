from openai import AsyncOpenAI
from app.config import settings
from app.core.llm.base import LLMProvider
from app.core.llm.fallback import FallbackLLM


class OpenAICompatibleLLM(LLMProvider):
    def __init__(self, api_key: str, base_url: str, model: str):
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.model = model

    async def astream(self, messages: list[dict]):
        stream = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            stream=True,
        )
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content


def get_llm() -> LLMProvider:
    providers = []
    priority = settings.llm_priority_list

    for name in priority:
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
                "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "qwen-turbo"))

    if not providers:
        raise RuntimeError("No LLM providers configured")
    return FallbackLLM(providers)

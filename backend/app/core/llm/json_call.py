"""Structured JSON generation via the LLM (thinking disabled by default).

Shared by the red-green task engine, the builder and other background jobs.
Task-style generation is structured JSON, so chain-of-thought only adds
minutes of latency (qwen3.8-max TTFT ~126s with thinking on vs ~9s without).
"""
import asyncio
import json
import re

from app.config import settings
from app.core.llm.factory import get_llm
from app.core.llm.usage import record_usage


def extract_json(text: str) -> dict | None:
    text = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None


async def _collect(stream, parts: list[str]) -> tuple[str, dict | None]:
    usage: dict | None = None
    async for item in stream:
        if isinstance(item, str):
            parts.append(item)
        elif item.get("type") == "content":
            parts.append(item.get("content") or "")
        elif item.get("type") == "usage":
            usage = item.get("usage")
    return "".join(parts), usage


async def _ask(prompt: str, timeout: int) -> tuple[str, dict | None]:
    messages = [{"role": "user", "content": prompt}]
    llm = get_llm()

    # Prefer function-calling stream because it carries real token usage.
    # Degrade to plain text for providers that reject tools or extra_body.
    factories = [
        lambda: llm.astream_with_tools(messages, [], extra_body={"enable_thinking": False}),
        lambda: llm.astream_with_tools(messages, []),
        lambda: llm.astream(messages),
    ]
    last_exc: Exception | None = None
    for factory in factories:
        parts: list[str] = []
        try:
            async with asyncio.timeout(timeout):
                text, usage = await _collect(factory(), parts)
            return text, usage
        except Exception as exc:  # noqa: BLE001
            if parts:
                raise
            last_exc = exc
    raise last_exc or RuntimeError("LLM call failed")


async def llm_json(
    prompt: str,
    timeout: int | None = None,
    attempts: int = 2,
    *,
    user_id: int | None = None,
    session_id: str | None = None,
    source: str = "json",
) -> dict:
    timeout = timeout or settings.task_llm_timeout

    text, usage = await _ask(prompt, timeout)
    await record_usage(user_id, session_id, usage, source=source)
    data = extract_json(text)

    if data is None and attempts > 1:
        text, usage = await _ask(
            prompt + "\n\n注意：只输出合法 JSON，不要任何解释文字。", timeout
        )
        await record_usage(user_id, session_id, usage, source=source)
        data = extract_json(text)

    if data is None:
        raise ValueError("模型未返回合法 JSON")
    return data

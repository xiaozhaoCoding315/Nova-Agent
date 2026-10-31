"""Native Anthropic Messages provider (tool use + prompt caching)."""
import json

import httpx

from app.config import settings
from app.core.llm.base import LLMProvider


def _to_anthropic(messages: list[dict]) -> tuple[str, list[dict]]:
    """Convert OpenAI-style messages to Anthropic system + messages blocks."""
    system_parts: list[str] = []
    converted: list[dict] = []

    for message in messages:
        role = message.get("role")
        if role == "system":
            content = message.get("content")
            if content:
                system_parts.append(str(content))
            continue

        if role == "tool":
            block = {
                "type": "tool_result",
                "tool_use_id": message.get("tool_call_id") or "",
                "content": str(message.get("content") or ""),
            }
            if converted and converted[-1]["role"] == "user":
                converted[-1]["content"].append(block)
            else:
                converted.append({"role": "user", "content": [block]})
            continue

        if role == "assistant":
            blocks: list[dict] = [
                block
                for block in message.get("thinking_blocks") or []
                if isinstance(block, dict)
                and block.get("type") in ("thinking", "redacted_thinking")
            ]
            text = message.get("content")
            if text:
                blocks.append({"type": "text", "text": str(text)})
            for call in message.get("tool_calls") or []:
                function = call.get("function") or {}
                try:
                    args = json.loads(function.get("arguments") or "{}")
                except (json.JSONDecodeError, TypeError):
                    args = {}
                blocks.append({
                    "type": "tool_use",
                    "id": call.get("id") or "",
                    "name": function.get("name") or "",
                    "input": args,
                })
            if blocks:
                converted.append({"role": "assistant", "content": blocks})
            continue

        converted.append({
            "role": "user",
            "content": [{"type": "text", "text": str(message.get("content") or "")}],
        })

    merged: list[dict] = []
    for item in converted:
        if merged and merged[-1]["role"] == item["role"]:
            merged[-1]["content"].extend(item["content"])
        else:
            merged.append(item)
    if not merged:
        merged = [{"role": "user", "content": [{"type": "text", "text": " "}]}]
    return "\n\n".join(system_parts), merged


def _tools_payload(tools: list[dict], caching: bool) -> list[dict]:
    payload = []
    for tool in tools:
        function = tool.get("function") or {}
        payload.append({
            "name": function.get("name") or "",
            "description": function.get("description") or "",
            "input_schema": function.get("parameters") or {"type": "object"},
        })
    if caching and payload:
        payload[-1]["cache_control"] = {"type": "ephemeral"}
    return payload


EFFORT_MAX_TOKENS = {"low": 8_192, "medium": 16_384, "high": 32_768}


class AnthropicLLM(LLMProvider):
    supports_tools = True

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.anthropic.com",
        model: str = "claude-sonnet-5-5",
        max_tokens: int | None = None,
        caching: bool | None = None,
        reasoning_effort: str | None = None,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.max_tokens = max_tokens or settings.anthropic_max_tokens
        self.caching = settings.anthropic_prompt_caching if caching is None else caching
        self.context_window: int | None = settings.anthropic_context_window
        self.reasoning_effort = (reasoning_effort or "").strip().lower() or None

    def _payload(self, messages: list[dict], tools: list[dict]) -> dict:
        system, converted = _to_anthropic(messages)
        payload: dict = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": converted,
            "stream": True,
        }
        if self.reasoning_effort:
            payload["thinking"] = {"type": "adaptive"}
            payload["output_config"] = {"effort": self.reasoning_effort}
            floor = EFFORT_MAX_TOKENS.get(self.reasoning_effort)
            if floor:
                payload["max_tokens"] = max(int(payload["max_tokens"]), floor)
        if system:
            if self.caching:
                payload["system"] = [{
                    "type": "text", "text": system,
                    "cache_control": {"type": "ephemeral"},
                }]
            else:
                payload["system"] = system
        tool_payload = _tools_payload(tools, self.caching)
        if tool_payload:
            payload["tools"] = tool_payload
        return payload

    def _headers(self) -> dict:
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        if self.caching:
            headers["anthropic-beta"] = "prompt-caching-2024-07-31"
        return headers

    async def astream(self, messages: list[dict], **kwargs):
        async for event in self.astream_with_tools(messages, [], **kwargs):
            if event.get("type") == "content":
                yield event["content"]

    async def astream_with_tools(self, messages: list[dict], tools: list[dict], **kwargs):
        payload = self._payload(messages, tools)
        usage: dict = {"model": self.model, "prompt_tokens": 0, "completion_tokens": 0}
        tool_blocks: dict[int, dict] = {}
        thinking_blocks: dict[int, dict] = {}
        finish_reason = "stop"

        async with httpx.AsyncClient(timeout=settings.llm_timeout) as client:
            async with client.stream(
                "POST", f"{self.base_url}/v1/messages",
                json=payload, headers=self._headers(),
            ) as response:
                if response.status_code != 200:
                    body = (await response.aread()).decode("utf-8", "replace")
                    raise RuntimeError(
                        f"Anthropic API {response.status_code}: {body[:500]}"
                    )
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if not raw:
                        continue
                    data = json.loads(raw)
                    event_type = data.get("type")

                    if event_type == "message_start":
                        start_usage = (data.get("message") or {}).get("usage") or {}
                        cached = int(
                            (start_usage.get("cache_read_input_tokens") or 0)
                            + (start_usage.get("cache_creation_input_tokens") or 0)
                        )
                        usage["prompt_tokens"] = int(
                            start_usage.get("input_tokens") or 0
                        ) + cached
                        usage["cached_tokens"] = cached
                    elif event_type == "content_block_start":
                        block = data.get("content_block") or {}
                        index = int(data.get("index") or 0)
                        if block.get("type") == "thinking":
                            thinking_blocks[index] = {
                                "type": "thinking", "thinking": "", "signature": "",
                            }
                        elif block.get("type") == "redacted_thinking":
                            thinking_blocks[index] = {
                                "type": "redacted_thinking",
                                "data": block.get("data") or "",
                            }
                        elif block.get("type") == "tool_use":
                            tool_blocks[index] = {
                                "id": block.get("id") or "",
                                "name": block.get("name") or "",
                                "arguments": "",
                            }
                    elif event_type == "content_block_delta":
                        delta = data.get("delta") or {}
                        index = int(data.get("index") or 0)
                        if delta.get("type") == "thinking_delta":
                            if index in thinking_blocks:
                                thinking_blocks[index]["thinking"] += delta.get("thinking") or ""
                        elif delta.get("type") == "signature_delta":
                            if index in thinking_blocks:
                                thinking_blocks[index]["signature"] += delta.get("signature") or ""
                        elif delta.get("type") == "text_delta" and delta.get("text"):
                            yield {"type": "content", "content": delta["text"]}
                        elif delta.get("type") == "input_json_delta":
                            slot = tool_blocks.setdefault(
                                index, {"id": "", "name": "", "arguments": ""},
                            )
                            slot["arguments"] += delta.get("partial_json") or ""
                    elif event_type == "message_delta":
                        delta = data.get("delta") or {}
                        finish_reason = delta.get("stop_reason") or finish_reason
                        delta_usage = data.get("usage") or {}
                        if delta_usage.get("output_tokens") is not None:
                            usage["completion_tokens"] = int(delta_usage["output_tokens"])
                    elif event_type == "error":
                        error = data.get("error") or {}
                        raise RuntimeError(
                            f"Anthropic stream error: {error.get('message') or error}"
                        )

        if tool_blocks:
            captured = [
                block for _, block in sorted(thinking_blocks.items())
                if (
                    (block["type"] == "thinking"
                     and (block["signature"] or block["thinking"]))
                    or (block["type"] == "redacted_thinking" and block["data"])
                )
            ]
            if captured:
                yield {"type": "thinking_blocks", "thinking_blocks": captured}
            yield {
                "type": "tool_calls",
                "tool_calls": [
                    {
                        "id": slot["id"],
                        "name": slot["name"],
                        "arguments": slot["arguments"] or "{}",
                    }
                    for _, slot in sorted(tool_blocks.items())
                ],
            }
            finish_reason = "tool_calls"
        yield {"type": "usage", "usage": usage}
        yield {"type": "finish", "finish_reason": finish_reason}

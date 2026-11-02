"""Anthropic message/tool conversion (no network)."""
import base64
import json

import httpx
import pytest

from app.core.llm import anthropic as anthropic_mod
from app.core.llm.anthropic import AnthropicLLM, _to_anthropic, _tools_payload

MESSAGES = [
    {"role": "system", "content": "you are a coding agent"},
    {"role": "user", "content": "read it"},
    {
        "role": "assistant",
        "content": "checking",
        "tool_calls": [{
            "id": "t1", "type": "function",
            "function": {"name": "read_file", "arguments": json.dumps({"path": "a.py"})},
        }],
    },
    {"role": "tool", "tool_call_id": "t1", "name": "read_file", "content": "print(1)"},
    {"role": "tool", "tool_call_id": "t2", "name": "grep", "content": "hit"},
]


def test_conversion_keeps_system_and_merges_tool_results():
    system, messages = _to_anthropic(MESSAGES)

    assert system == "you are a coding agent"
    assert messages[0]["role"] == "user"
    assistant = messages[1]
    assert assistant["content"][0] == {"type": "text", "text": "checking"}
    tool_use = assistant["content"][1]
    assert tool_use["type"] == "tool_use"
    assert tool_use["id"] == "t1"
    assert tool_use["input"] == {"path": "a.py"}
    # Consecutive tool messages become one user message with two blocks.
    assert messages[2]["role"] == "user"
    assert [block["type"] for block in messages[2]["content"]] == [
        "tool_result", "tool_result",
    ]


def test_tools_payload_adds_cache_control():
    tools = [{
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "read",
            "parameters": {"type": "object", "properties": {}},
        },
    }]
    payload = _tools_payload(tools, caching=True)
    assert payload[0]["input_schema"] == {"type": "object", "properties": {}}
    assert payload[0]["cache_control"] == {"type": "ephemeral"}

    assert "cache_control" not in _tools_payload(tools, caching=False)[0]


def test_payload_caches_system_when_enabled():
    llm = AnthropicLLM("key", model="claude-sonnet-4-5", caching=True)
    payload = llm._payload([{"role": "system", "content": "sys"}], [])
    assert payload["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert llm.supports_tools is True

    plain = AnthropicLLM("key", caching=False)._payload(
        [{"role": "system", "content": "sys"}], []
    )
    assert plain["system"] == "sys"


@pytest.mark.parametrize(
    ("effort", "floor"),
    [("low", 8_192), ("medium", 16_384), ("high", 32_768)],
)
def test_payload_uses_adaptive_thinking_and_effort(effort, floor):
    llm = AnthropicLLM(
        "key", model="claude-sonnet-5-5", max_tokens=1024,
        reasoning_effort=effort,
    )

    payload = llm._payload([{"role": "user", "content": "hi"}], [])

    assert payload["thinking"] == {"type": "adaptive"}
    assert payload["output_config"] == {"effort": effort}
    assert "budget_tokens" not in json.dumps(payload)
    assert payload["max_tokens"] == floor


def test_payload_without_effort_omits_thinking_config():
    llm = AnthropicLLM("key", model="claude-sonnet-5-5", max_tokens=1024)

    payload = llm._payload([{"role": "user", "content": "hi"}], [])

    assert "thinking" not in payload
    assert "output_config" not in payload
    assert payload["max_tokens"] == 1024


def test_assistant_thinking_blocks_are_replayed_first():
    messages = [
        {"role": "user", "content": "read it"},
        {
            "role": "assistant",
            "content": "checking",
            "thinking_blocks": [
                {"type": "thinking", "thinking": "", "signature": "sig-1"},
                {"type": "text", "text": "not a thinking block"},
            ],
            "tool_calls": [{
                "id": "t1", "type": "function",
                "function": {"name": "read_file", "arguments": json.dumps({"path": "a.py"})},
            }],
        },
        {"role": "tool", "tool_call_id": "t1", "name": "read_file", "content": "print(1)"},
    ]

    _, converted = _to_anthropic(messages)

    blocks = converted[1]["content"]
    assert [block["type"] for block in blocks] == ["thinking", "text", "tool_use"]
    assert blocks[0] == {"type": "thinking", "thinking": "", "signature": "sig-1"}


@pytest.mark.asyncio
async def test_stream_emits_thinking_blocks_before_tool_calls(monkeypatch):
    stream_events = [
        {"type": "message_start", "message": {"usage": {"input_tokens": 10}}},
        {"type": "content_block_start", "index": 0,
         "content_block": {"type": "thinking", "thinking": ""}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "thinking_delta", "thinking": "hmm"}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "signature_delta", "signature": "sig-1"}},
        {"type": "content_block_start", "index": 1,
         "content_block": {"type": "tool_use", "id": "t1", "name": "read_file"}},
        {"type": "content_block_delta", "index": 1,
         "delta": {"type": "input_json_delta", "partial_json": '{"path": "a.py"}'}},
        {"type": "message_delta", "delta": {"stop_reason": "tool_use"},
         "usage": {"output_tokens": 5}},
    ]
    body = "".join(f"data: {json.dumps(event)}\n\n" for event in stream_events)

    real_client = httpx.AsyncClient

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body.encode())

    def fake_client(**kwargs):
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(anthropic_mod.httpx, "AsyncClient", fake_client)

    llm = AnthropicLLM("key", model="claude-sonnet-5-5", reasoning_effort="high")
    events = [
        event
        async for event in llm.astream_with_tools(
            [{"role": "user", "content": "hi"}], []
        )
    ]

    types = [event["type"] for event in events]
    thinking_index = types.index("thinking_blocks")
    assert types.index("tool_calls") == thinking_index + 1
    assert events[thinking_index]["thinking_blocks"] == [
        {"type": "thinking", "thinking": "hmm", "signature": "sig-1"},
    ]
    tool_calls = events[types.index("tool_calls")]["tool_calls"]
    assert tool_calls[0]["arguments"] == '{"path": "a.py"}'


def _fake_stream(monkeypatch, stream_events):
    body = "".join(f"data: {json.dumps(event)}\n\n" for event in stream_events)
    real_client = httpx.AsyncClient

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body.encode())

    def fake_client(**kwargs):
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(anthropic_mod.httpx, "AsyncClient", fake_client)


async def _collect_stream(llm, messages):
    return [event async for event in llm.astream_with_tools(messages, [])]


@pytest.mark.asyncio
async def test_stream_captures_redacted_thinking_before_tool_calls(monkeypatch):
    _fake_stream(monkeypatch, [
        {"type": "message_start", "message": {"usage": {"input_tokens": 10}}},
        {"type": "content_block_start", "index": 0,
         "content_block": {"type": "redacted_thinking", "data": "opaque-blob"}},
        {"type": "content_block_start", "index": 1,
         "content_block": {"type": "tool_use", "id": "t1", "name": "read_file"}},
        {"type": "content_block_delta", "index": 1,
         "delta": {"type": "input_json_delta", "partial_json": '{"path": "a.py"}'}},
        {"type": "message_delta", "delta": {"stop_reason": "tool_use"},
         "usage": {"output_tokens": 5}},
    ])

    events = await _collect_stream(
        AnthropicLLM("key", model="claude-sonnet-5-5"),
        [{"role": "user", "content": "hi"}],
    )

    types = [event["type"] for event in events]
    thinking_index = types.index("thinking_blocks")
    assert types.index("tool_calls") == thinking_index + 1
    blocks = events[thinking_index]["thinking_blocks"]
    assert blocks == [{"type": "redacted_thinking", "data": "opaque-blob"}]

    _, converted = _to_anthropic([
        {"role": "user", "content": "hi"},
        {
            "role": "assistant", "content": "",
            "thinking_blocks": blocks,
            "tool_calls": [{
                "id": "t1", "type": "function",
                "function": {"name": "read_file", "arguments": '{"path": "a.py"}'},
            }],
        },
        {"role": "tool", "tool_call_id": "t1", "name": "read_file", "content": "x"},
    ])
    assistant_blocks = converted[1]["content"]
    assert assistant_blocks[0] == {"type": "redacted_thinking", "data": "opaque-blob"}
    assert [block["type"] for block in assistant_blocks] == [
        "redacted_thinking", "tool_use",
    ]


@pytest.mark.asyncio
async def test_stream_keeps_thinking_and_redacted_blocks_in_index_order(monkeypatch):
    _fake_stream(monkeypatch, [
        {"type": "content_block_start", "index": 0,
         "content_block": {"type": "thinking", "thinking": ""}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "thinking_delta", "thinking": "consider"}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "signature_delta", "signature": "sig-1"}},
        {"type": "content_block_start", "index": 1,
         "content_block": {"type": "redacted_thinking", "data": "blob-1"}},
        {"type": "content_block_start", "index": 2,
         "content_block": {"type": "tool_use", "id": "t1", "name": "grep"}},
        {"type": "content_block_delta", "index": 2,
         "delta": {"type": "input_json_delta", "partial_json": "{}"}},
        {"type": "message_delta", "delta": {"stop_reason": "tool_use"}},
    ])

    events = await _collect_stream(
        AnthropicLLM("key"), [{"role": "user", "content": "hi"}],
    )

    blocks = next(
        event["thinking_blocks"] for event in events
        if event["type"] == "thinking_blocks"
    )
    assert blocks == [
        {"type": "thinking", "thinking": "consider", "signature": "sig-1"},
        {"type": "redacted_thinking", "data": "blob-1"},
    ]


def test_user_image_content_converts_to_base64_image_block():
    raw = b"\x89PNG\r\n\x1a\n" + b"0" * 16
    encoded = base64.b64encode(raw).decode("ascii")
    url = f"data:image/png;base64,{encoded}"
    _, messages = _to_anthropic([{
        "role": "user",
        "content": [
            {"type": "text", "text": "看图"},
            {"type": "image_url", "image_url": {"url": url}},
            {"type": "image_url", "image_url": {"url": "https://example.com/a.png"}},
        ],
    }])
    blocks = messages[0]["content"]
    assert blocks[0] == {"type": "text", "text": "看图"}
    assert blocks[1] == {
        "type": "image",
        "source": {
            "type": "base64", "media_type": "image/png", "data": encoded,
        },
    }
    assert len(blocks) == 2


def test_anthropic_declares_vision():
    assert AnthropicLLM.supports_vision is True

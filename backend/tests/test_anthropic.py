"""Anthropic message/tool conversion (no network)."""
import json

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

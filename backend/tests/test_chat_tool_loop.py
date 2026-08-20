"""Chat loop function-calling integration: tool_call/tool_result SSE events."""
import json
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch

from app.main import app


class FakeToolLLM:
    """Round 1: request the calculator tool. Round 2: stream the final answer."""

    def __init__(self):
        self.rounds = 0
        self.seen_messages: list[list[dict]] = []

    async def astream_with_tools(self, messages, tools):
        self.rounds += 1
        self.seen_messages.append(messages)
        if self.rounds == 1:
            yield {
                "type": "tool_calls",
                "tool_calls": [
                    {"id": "call_1", "name": "calculator",
                     "arguments": json.dumps({"expression": "2*(3+4)"})}
                ],
            }
            yield {"type": "finish", "finish_reason": "tool_calls"}
        else:
            yield {"type": "content", "content": "计算结果是 14"}
            yield {"type": "finish", "finish_reason": "stop"}


def _collect_events(resp) -> list[dict]:
    events = []
    for chunk in resp.iter_bytes():
        text = chunk.decode("utf-8")
        for line in text.splitlines():
            if line.startswith("data: "):
                try:
                    events.append(json.loads(line[6:]))
                except json.JSONDecodeError:
                    pass
    return events


def test_chat_tool_call_loop_emits_sse_events():
    async def fake_retrieve(q, top_k=5):
        return []

    async def fake_memory(*args, **kwargs):
        return ""

    fake_llm = FakeToolLLM()

    with patch("app.api.v1.chat.retrieve", new=fake_retrieve), \
         patch("app.api.v1.chat.get_llm", return_value=fake_llm), \
         patch("app.api.v1.chat.add_message", new=AsyncMock()), \
         patch("app.api.v1.chat.assemble_context", new=fake_memory), \
         patch("app.api.v1.chat.check_should_archive", new=AsyncMock(return_value=False)):
        with TestClient(app).stream(
            "POST", "/api/v1/chat/message",
            json={"message": "帮我算 2*(3+4)"},
        ) as resp:
            assert resp.status_code == 200
            events = _collect_events(resp)

    types = [e["type"] for e in events]
    assert "tool_call" in types
    assert "tool_result" in types

    tool_call = next(e for e in events if e["type"] == "tool_call")
    assert tool_call["name"] == "calculator"
    assert "expression" in tool_call["arguments"]

    tool_result = next(e for e in events if e["type"] == "tool_result")
    assert tool_result["result"]["ok"] is True
    assert tool_result["result"]["result"] == 14
    assert "duration_ms" in tool_result

    done = next(e for e in events if e["type"] == "done")
    assert done["tools_used"] == ["calculator"]

    # LLM round 2 must receive the tool result message
    second_round_msgs = fake_llm.seen_messages[1]
    tool_msgs = [m for m in second_round_msgs if m.get("role") == "tool"]
    assert len(tool_msgs) == 1
    assert tool_msgs[0]["tool_call_id"] == "call_1"
    assert "14" in tool_msgs[0]["content"]

    # assistant tool_calls decision must be recorded in messages
    assistant_msgs = [m for m in second_round_msgs if m.get("role") == "assistant"]
    assert any(m.get("tool_calls") for m in assistant_msgs)

    # final streamed answer reaches the client
    tokens = "".join(e.get("content", "") for e in events if e["type"] == "token")
    assert "14" in tokens


def test_chat_tool_error_does_not_break_stream():
    """An unknown tool requested by the LLM must degrade, not crash."""

    class BrokenLLM:
        async def astream_with_tools(self, messages, tools):
            yield {
                "type": "tool_calls",
                "tool_calls": [{"id": "c9", "name": "ghost_tool", "arguments": "{}"}],
            }
            yield {"type": "finish", "finish_reason": "tool_calls"}

    async def fake_retrieve(q, top_k=5):
        return []

    async def fake_memory(*args, **kwargs):
        return ""

    with patch("app.api.v1.chat.retrieve", new=fake_retrieve), \
         patch("app.api.v1.chat.get_llm", return_value=BrokenLLM()), \
         patch("app.api.v1.chat.add_message", new=AsyncMock()), \
         patch("app.api.v1.chat.assemble_context", new=fake_memory), \
         patch("app.api.v1.chat.check_should_archive", new=AsyncMock(return_value=False)):
        with TestClient(app).stream(
            "POST", "/api/v1/chat/message",
            json={"message": "调用不存在的工具"},
        ) as resp:
            assert resp.status_code == 200
            events = _collect_events(resp)

    tool_result = next(e for e in events if e["type"] == "tool_result")
    assert tool_result["result"]["ok"] is False
    done = next(e for e in events if e["type"] == "done")
    # A stubborn LLM requesting a bogus tool every round is capped at
    # MAX_TOOL_ROUNDS (4) instead of looping forever.
    assert done["tools_used"] == ["ghost_tool"] * 4

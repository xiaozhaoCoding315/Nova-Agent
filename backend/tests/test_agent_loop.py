"""Agent loop tests: SSE event protocol, tool rounds, timeout, stop semantics."""
import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from app.core.agent import loop as loop_mod

USER = {"id": 1, "username": "admin", "role": "admin"}
SESSION = {"id": "11111111-1111-1111-1111-111111111111", "title": "t"}


class FakeLLM:
    def __init__(self, scripts):
        self.scripts = list(scripts)

    async def astream_with_tools(self, messages, tools):
        for event in self.scripts.pop(0):
            yield event


class SlowLLM:
    async def astream_with_tools(self, messages, tools):
        await asyncio.sleep(5)
        yield {"type": "content", "content": "late"}


def _patch_common(monkeypatch, llm):
    async def _get_llm(*_args, **_kwargs):
        return llm

    monkeypatch.setattr(loop_mod, "get_llm", _get_llm)
    monkeypatch.setattr(loop_mod, "retrieve", AsyncMock(return_value=[]))
    monkeypatch.setattr(loop_mod.session_mod, "recent_messages", AsyncMock(return_value=[]))
    monkeypatch.setattr(loop_mod.session_mod, "add_message", AsyncMock(return_value=101))
    monkeypatch.setattr(loop_mod.facts_mod, "get_relevant_facts", AsyncMock(return_value=[]))
    monkeypatch.setattr(loop_mod.facts_mod, "extract_facts_from_turn", AsyncMock(return_value=0))
    monkeypatch.setattr(loop_mod, "log_audit", AsyncMock())
    monkeypatch.setattr(loop_mod, "_record_usage", AsyncMock())


async def _collect(gen):
    events = []
    async for event in gen:
        events.append(event)
    return events


@pytest.mark.asyncio
async def test_plain_answer_event_sequence(monkeypatch):
    llm = FakeLLM([[
        {"type": "content", "content": "你好"},
        {"type": "usage", "usage": {"prompt_tokens": 10, "completion_tokens": 2, "model": "test"}},
        {"type": "finish", "finish_reason": "stop"},
    ]])
    _patch_common(monkeypatch, llm)

    events = await _collect(loop_mod.run_chat(USER, SESSION, "hi", []))

    names = [e["event"] for e in events]
    assert names == ["meta", "retrieval", "context", "token", "usage", "evidence", "done"]
    assert events[3]["data"]["text"] == "你好"
    assert events[4]["data"]["prompt_tokens"] == 10
    context_event = events[2]["data"]
    assert context_event["window"] > 0
    assert "系统提示" in context_event["sections"]
    assert events[-1]["data"]["message_id"] == 101
    assert events[-1]["data"]["tools_used"] == []
    report = events[-1]["data"]["report"]
    assert report["status"] in ("verified", "partial", "unverified")
    assert report["stats"]["rounds"] == 1
    tool_json = loop_mod.session_mod.add_message.await_args.kwargs["tool_json"]
    assert "report" in tool_json


@pytest.mark.asyncio
async def test_tool_round_executes_registry_and_loops(monkeypatch):
    tool_args = json.dumps({"input": '{"a": 1}'})
    llm = FakeLLM([
        [
            {"type": "content", "content": "查一下…"},
            {"type": "tool_calls", "tool_calls": [
                {"id": "t1", "name": "json_tool", "arguments": tool_args}
            ]},
            {"type": "usage", "usage": {"prompt_tokens": 20, "completion_tokens": 5, "model": "test"}},
            {"type": "finish", "finish_reason": "tool_calls"},
        ],
        [
            {"type": "content", "content": "结果是 a=1"},
            {"type": "usage", "usage": {"prompt_tokens": 30, "completion_tokens": 6, "model": "test"}},
            {"type": "finish", "finish_reason": "stop"},
        ],
    ])
    _patch_common(monkeypatch, llm)

    events = await _collect(loop_mod.run_chat(USER, SESSION, "验证一下", []))
    names = [e["event"] for e in events]

    assert "tool_call" in names and "tool_result" in names
    tool_call = next(e for e in events if e["event"] == "tool_call")
    assert tool_call["data"]["round"] == 1
    tool_result = next(e for e in events if e["event"] == "tool_result")
    assert tool_result["data"]["ok"] is True
    assert tool_result["data"]["name"] == "json_tool"

    done = events[-1]["data"]
    assert done["tools_used"] == ["json_tool"]
    assert done["rounds"] == 2

    # Per-call details are persisted so history can re-render tool cards.
    tool_json = loop_mod.session_mod.add_message.await_args.kwargs["tool_json"]
    persisted = tool_json.get("tool_events") or []
    assert len(persisted) == 1
    assert persisted[0]["name"] == "json_tool"
    assert persisted[0]["ok"] is True
    assert persisted[0]["round"] == 1
    assert persisted[0]["preview"]


@pytest.mark.asyncio
async def test_llm_timeout_emits_error_event(monkeypatch):
    monkeypatch.setattr(loop_mod.settings, "llm_timeout", 1)
    _patch_common(monkeypatch, SlowLLM())
    monkeypatch.setattr(loop_mod.settings, "llm_timeout", 0.05)

    events = await _collect(loop_mod.run_chat(USER, SESSION, "hi", []))
    error = next(e for e in events if e["event"] == "error")
    assert error["data"]["code"] == "llm_timeout"


@pytest.mark.asyncio
async def test_stop_mid_stream_persists_partial_output(monkeypatch):
    llm = FakeLLM([[
        {"type": "content", "content": "部分"},
        {"type": "content", "content": "内容"},
        {"type": "finish", "finish_reason": "stop"},
    ]])
    _patch_common(monkeypatch, llm)

    gen = loop_mod.run_chat(USER, SESSION, "hi", [])
    seen = []
    async for event in gen:
        seen.append(event["event"])
        if event["event"] == "token":
            break
    await gen.aclose()
    # Disconnect path persists via a background task so the cancelled request
    # cannot interrupt the DB write.
    for _ in range(20):
        await asyncio.sleep(0.01)
        if loop_mod.session_mod.add_message.await_count:
            break

    assert seen == ["meta", "retrieval", "context", "token"]
    loop_mod.session_mod.add_message.assert_awaited()
    content = loop_mod.session_mod.add_message.await_args.args[2]
    assert content == "部分"


@pytest.mark.asyncio
async def test_context_includes_facts_in_system_prompt(monkeypatch):
    captured = {}

    class CapturingLLM(FakeLLM):
        async def astream_with_tools(self, messages, tools):
            captured["messages"] = messages
            async for e in super().astream_with_tools(messages, tools):
                yield e

    llm = CapturingLLM([[{"type": "content", "content": "ok"}, {"type": "finish", "finish_reason": "stop"}]])
    _patch_common(monkeypatch, llm)
    monkeypatch.setattr(loop_mod.facts_mod, "get_relevant_facts", AsyncMock(return_value=["用户偏好 Java 后端"]))

    await _collect(loop_mod.run_chat(USER, SESSION, "hi", []))

    system = captured["messages"][0]
    assert system["role"] == "system"
    assert "用户偏好 Java 后端" in system["content"]

@pytest.mark.asyncio
async def test_rounds_exhausted_emits_incomplete_notice(monkeypatch):
    llm = FakeLLM([[
        {"type": "tool_calls", "tool_calls": [
            {"id": "t1", "name": "json_tool", "arguments": json.dumps({"input": '{"a": 1}'})}
        ]},
        {"type": "finish", "finish_reason": "tool_calls"},
    ]])
    _patch_common(monkeypatch, llm)
    monkeypatch.setattr(loop_mod.settings, "max_rounds", 1)
    monkeypatch.setattr(loop_mod.settings, "max_continuations", 0)

    events = await _collect(loop_mod.run_chat(USER, SESSION, "hi", []))
    notices = [e for e in events if e["event"] == "notice" and e["data"].get("kind") == "incomplete"]
    assert notices


@pytest.mark.asyncio
async def test_max_rounds_auto_continues(monkeypatch):
    llm = FakeLLM([
        [
            {"type": "tool_calls", "tool_calls": [
                {"id": "t1", "name": "json_tool", "arguments": json.dumps({"input": '{"a": 1}'})}
            ]},
            {"type": "finish", "finish_reason": "tool_calls"},
        ],
        [
            {"type": "content", "content": "完成了"},
            {"type": "finish", "finish_reason": "stop"},
        ],
    ])
    _patch_common(monkeypatch, llm)
    monkeypatch.setattr(loop_mod.settings, "max_rounds", 1)
    monkeypatch.setattr(loop_mod.settings, "max_continuations", 1)

    events = await _collect(loop_mod.run_chat(USER, SESSION, "hi", []))
    kinds = [e["data"].get("kind") for e in events if e["event"] == "notice"]
    assert "continued" in kinds
    assert "incomplete" not in kinds
    assert any(e["event"] == "token" and e["data"]["text"] == "完成了" for e in events)


@pytest.mark.asyncio
async def test_llm_failure_without_output_auto_continues(monkeypatch):
    class FlakyThenOk:
        def __init__(self):
            self.calls = 0

        async def astream_with_tools(self, messages, tools):
            self.calls += 1
            if self.calls == 1:
                raise ConnectionError("provider hiccup")
            yield {"type": "content", "content": "续上了"}
            yield {"type": "finish", "finish_reason": "stop"}

    _patch_common(monkeypatch, FlakyThenOk())
    monkeypatch.setattr(loop_mod.settings, "llm_round_retries", 0)
    monkeypatch.setattr(loop_mod.settings, "max_continuations", 1)

    events = await _collect(loop_mod.run_chat(USER, SESSION, "hi", []))
    kinds = [e["data"].get("kind") for e in events if e["event"] == "notice"]
    assert "continued" in kinds
    assert any(e["event"] == "token" and e["data"]["text"] == "续上了" for e in events)

"""Parent loop: subagent SSE events and tool_json.subagents persistence."""
import json
from unittest.mock import AsyncMock

import pytest

from app.core.agent import loop as loop_mod

USER = {"id": 1, "username": "admin", "role": "admin"}
SESSION = {
    "id": "11111111-1111-1111-1111-111111111111",
    "title": "t",
    "permission_mode": "ask",
    "model": "session-model",
    "llm_overrides": {"temperature": 0.3},
}


class FakeLLM:
    def __init__(self, scripts):
        self.scripts = list(scripts)

    async def astream_with_tools(self, messages, tools):
        for event in self.scripts.pop(0):
            yield event


class FakeTool:
    name = "spawn_agents"
    streaming = True
    parallel_safe = False


class FakeRegistry:
    def __init__(self):
        self.ctx = None

    def specs(self, **_kwargs):
        return [{
            "type": "function",
            "function": {"name": "spawn_agents", "description": "", "parameters": {}},
        }]

    def get(self, name):
        return FakeTool() if name == "spawn_agents" else None

    async def execute(self, name, args, ctx):
        self.ctx = ctx
        payload = {
            "id": "sa-1", "title": "调研", "status": "ok", "summary": "结论",
            "findings": [], "files": [], "rounds": 1, "tools": ["grep"],
            "tokens": {"prompt": 1, "completion": 1}, "ms": 5,
            "citations": {"verified": 0, "missing": 0, "out_of_range": 0, "skipped": 0, "executed": False},
            "error": None,
        }
        await ctx.output_queue.put(("subagent", json.dumps({
            "phase": "start", "id": "sa-1", "title": "调研",
        })))
        await ctx.output_queue.put(("subagent", json.dumps({
            "phase": "done", **payload,
        })))
        return {"ok": True, "output": {
            "tasks": [payload], "total": 1, "ok_count": 1, "note": "",
        }, "ms": 5, "business": False}


async def _collect(gen):
    return [event async for event in gen]


@pytest.mark.asyncio
async def test_parent_loop_emits_subagent_events_and_persists(monkeypatch):
    llm = FakeLLM([
        [
            {"type": "content", "content": "我并行查一下。"},
            {"type": "tool_calls", "tool_calls": [{
                "id": "call-1", "name": "spawn_agents",
                "arguments": json.dumps({"tasks": [
                    {"title": "调研", "prompt": "找出鉴权中间件并给出文件行号"},
                ]}),
            }]},
            {"type": "usage", "usage": {"prompt_tokens": 10, "completion_tokens": 2, "model": "test"}},
        ],
        [
            {"type": "content", "content": "完成"},
            {"type": "usage", "usage": {"prompt_tokens": 20, "completion_tokens": 3, "model": "test"}},
        ],
    ])

    async def _get_llm(*_args, overrides=None, **_kwargs):
        return llm

    registry = FakeRegistry()
    monkeypatch.setattr(loop_mod, "get_llm", _get_llm)
    monkeypatch.setattr(loop_mod, "get_registry", lambda: registry)
    monkeypatch.setattr(loop_mod, "retrieve", AsyncMock(return_value=[]))
    monkeypatch.setattr(loop_mod.session_mod, "recent_messages", AsyncMock(return_value=[]))
    monkeypatch.setattr(loop_mod.session_mod, "add_message", AsyncMock(return_value=101))
    monkeypatch.setattr(loop_mod.facts_mod, "get_relevant_facts", AsyncMock(return_value=[]))
    monkeypatch.setattr(loop_mod.facts_mod, "extract_facts_from_turn", AsyncMock(return_value=0))
    monkeypatch.setattr(loop_mod, "log_audit", AsyncMock())
    monkeypatch.setattr(loop_mod, "_record_usage", AsyncMock())
    monkeypatch.setattr(loop_mod, "local_agent_online", AsyncMock(return_value=False))
    monkeypatch.setattr(loop_mod, "trace_record", AsyncMock())
    monkeypatch.setattr(loop_mod, "ensure_token_budget", AsyncMock())

    events = await _collect(loop_mod.run_chat(USER, SESSION, "并行调研", ["r1"]))

    subagent_events = [event for event in events if event["event"] == "subagent"]
    assert [event["data"]["phase"] for event in subagent_events] == ["start", "done"]
    assert subagent_events[1]["data"]["summary"] == "结论"
    assert registry.ctx.model == "session-model"
    assert registry.ctx.llm_overrides == {"temperature": 0.3}
    assert registry.ctx.turn_id == events[0]["data"]["turn_id"]

    tool_json = loop_mod.session_mod.add_message.await_args.kwargs["tool_json"]
    assert tool_json["subagents"][0]["id"] == "sa-1"
    assert tool_json["subagents"][0]["summary"] == "结论"
    assert events[-1]["data"]["tools_used"] == ["spawn_agents"]

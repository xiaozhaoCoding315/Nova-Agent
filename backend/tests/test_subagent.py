"""Sub-agent runner: rounds, limits, tools, events, usage."""
import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from app.core.agent import subagent as subagent_mod
from app.core.llm.factory import LLMNotConfiguredError

USER = {"id": 1, "username": "admin", "role": "admin"}


class FakeLLM:
    supports_tools = True
    model = "fake-model"
    context_window = 100_000

    def __init__(self, rounds, final="## 结论\n最终总结"):
        self.rounds = list(rounds)
        self.final = final
        self.calls = []

    async def astream_with_tools(self, messages, tools):
        self.calls.append({
            "messages": [dict(message) for message in messages],
            "tools": list(tools),
        })
        events = self.rounds.pop(0) if self.rounds else []
        for event in events:
            yield event

    async def astream(self, messages):
        yield self.final


class FakeRegistry:
    def __init__(self, results=None):
        self.results = results or {}
        self.executed = []

    def specs(self, **_kwargs):
        names = set(subagent_mod.SUBAGENT_TOOL_ALLOWLIST) | {"write_files", "run_command"}
        return [
            {"type": "function", "function": {"name": name, "description": "", "parameters": {}}}
            for name in sorted(names)
        ]

    async def execute(self, name, args, ctx):
        self.executed.append((name, args, ctx))
        return self.results.get(
            name,
            {"ok": True, "output": {"content": "ok"}, "ms": 1, "business": False},
        )


def _patch(monkeypatch, llm, citations=None):
    async def _get_llm(*_args, **_kwargs):
        return llm

    monkeypatch.setattr(subagent_mod, "get_llm", _get_llm)
    monkeypatch.setattr(subagent_mod, "ensure_token_budget", AsyncMock())
    monkeypatch.setattr(subagent_mod, "record_usage", AsyncMock())
    monkeypatch.setattr(subagent_mod, "trace_record", AsyncMock())
    monkeypatch.setattr(
        subagent_mod,
        "verify_citations",
        AsyncMock(return_value=citations or {
            "citations": [], "executed": False, "verified": 0,
            "missing": 0, "out_of_range": 0, "skipped": 0,
        }),
    )


async def _run(monkeypatch, llm, registry, **kwargs):
    _patch(monkeypatch, llm)
    events = []

    async def emit(payload):
        events.append(payload)

    result = await subagent_mod.run_subagent(
        user=USER, session_id="s1", turn_id="t1", task_id="sa-1",
        title="调研", prompt="找出鉴权中间件并给出文件行号", repo_ids=["r1"],
        repos=[{"id": "r1", "name": "repo", "rules": ""}],
        repo_roots={"r1": "C:/repo"},
        emit=emit, registry=registry, **kwargs,
    )
    return result, events


@pytest.mark.asyncio
async def test_subagent_runs_tool_round_then_summary(monkeypatch):
    llm = FakeLLM([
        [
            {"type": "content", "content": "先查一下"},
            {"type": "tool_calls", "tool_calls": [
                {"id": "t1", "name": "read_file", "arguments": json.dumps({"path": "src/auth.py"})}
            ]},
            {"type": "usage", "usage": {"prompt_tokens": 10, "completion_tokens": 2, "model": "fake-model"}},
        ],
        [
            {"type": "content", "content": (
                "## 结论\n鉴权在 src/auth.py:42。\n"
                "## 关键发现\n- [src/auth.py:42] 中间件入口"
            )},
            {"type": "usage", "usage": {"prompt_tokens": 20, "completion_tokens": 5, "model": "fake-model"}},
        ],
    ])
    registry = FakeRegistry()
    result, events = await _run(monkeypatch, llm, registry)

    assert result["status"] == "ok"
    assert result["rounds"] == 2
    assert result["tools"] == ["read_file"]
    assert "src/auth.py:42" in result["summary"]
    assert result["findings"][0]["file"] == "src/auth.py"
    assert result["findings"][0]["line"] == 42
    assert result["tokens"] == {"prompt": 30, "completion": 7}
    assert registry.executed[0][0] == "read_file"
    ctx = registry.executed[0][2]
    assert ctx.permission_mode == "readonly"
    assert ctx.repo_ids == ["r1"]
    tool_names = {spec["function"]["name"] for spec in llm.calls[0]["tools"]}
    assert tool_names
    assert tool_names <= subagent_mod.SUBAGENT_TOOL_ALLOWLIST
    assert "write_files" not in tool_names
    assert "run_command" not in tool_names
    assert [event["phase"] for event in events] == ["start", "round", "tool", "round", "done"]
    subagent_mod.record_usage.assert_awaited_once()
    assert subagent_mod.record_usage.await_args.kwargs["source"] == "subagent"


@pytest.mark.asyncio
async def test_subagent_preserves_thinking_blocks_across_tool_rounds(monkeypatch):
    thinking = [{"type": "thinking", "thinking": "先读文件", "signature": "sig"}]
    llm = FakeLLM([
        [
            {"type": "thinking_blocks", "thinking_blocks": thinking},
            {"type": "content", "content": "先查一下"},
            {"type": "tool_calls", "tool_calls": [
                {"id": "t1", "name": "read_file", "arguments": json.dumps({"path": "src/auth.py"})}
            ]},
        ],
        [
            {"type": "content", "content": "## 结论\n鉴权在 src/auth.py:42。"},
        ],
    ])
    result, _ = await _run(monkeypatch, llm, FakeRegistry())

    assert result["status"] == "ok"
    second_request = llm.calls[1]["messages"]
    assistant = next(
        message for message in second_request if message.get("role") == "assistant"
    )
    assert assistant["thinking_blocks"] == thinking


@pytest.mark.asyncio
async def test_subagent_partial_after_round_limit(monkeypatch):
    llm = FakeLLM([
        [{"type": "tool_calls", "tool_calls": [
            {"id": "t1", "name": "grep", "arguments": json.dumps({"pattern": "auth"})}
        ]}],
        [{"type": "tool_calls", "tool_calls": [
            {"id": "t2", "name": "grep", "arguments": json.dumps({"pattern": "login"})}
        ]}],
    ], final="## 结论\n达到上限后的总结")
    registry = FakeRegistry()
    result, _ = await _run(monkeypatch, llm, registry, max_rounds=2)

    assert result["status"] == "partial"
    assert result["rounds"] == 2
    assert "达到上限后的总结" in result["summary"]


@pytest.mark.asyncio
async def test_subagent_timeout(monkeypatch):
    class SlowLLM(FakeLLM):
        async def astream_with_tools(self, messages, tools):
            await asyncio.sleep(3)
            yield {"type": "content", "content": "late"}

    result, events = await _run(monkeypatch, SlowLLM([]), FakeRegistry(), timeout=1.0)

    assert result["status"] == "timeout"
    assert "超过 1 秒" in result["error"]
    assert result["ms"] >= 1000
    assert events[-1]["phase"] == "done"


@pytest.mark.asyncio
async def test_subagent_rejects_tool_outside_allowlist(monkeypatch):
    llm = FakeLLM([
        [{"type": "tool_calls", "tool_calls": [
            {"id": "t1", "name": "write_files", "arguments": "{}"}
        ]}],
        [{"type": "content", "content": "## 结论\n只读完成"}],
    ])
    registry = FakeRegistry()
    result, _ = await _run(monkeypatch, llm, registry)

    assert registry.executed == []
    assert result["tools"] == ["write_files"]
    assert result["status"] == "ok"


@pytest.mark.asyncio
async def test_subagent_config_error_is_reported(monkeypatch):
    async def _boom(*_args, **_kwargs):
        raise LLMNotConfiguredError("请先配置模型 Key")

    _patch(monkeypatch, FakeLLM([]))
    monkeypatch.setattr(subagent_mod, "get_llm", _boom)
    result = await subagent_mod.run_subagent(
        user=USER, session_id="s1", turn_id="t1", task_id="sa-1",
        title="调研", prompt="找出鉴权中间件并给出文件行号", repo_ids=["r1"],
        repos=[], repo_roots={}, registry=FakeRegistry(),
    )

    assert result["status"] == "failed"
    assert "请先配置模型 Key" in result["error"]

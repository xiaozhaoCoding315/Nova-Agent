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
    monkeypatch.setattr(loop_mod, "local_agent_online", AsyncMock(return_value=False))


async def _collect(gen):
    events = []
    async for event in gen:
        events.append(event)
    return events


@pytest.mark.asyncio
async def test_auto_edit_enqueues_reindex(monkeypatch):
    from app.core.jobs import service as jobs_service
    from app.core.tools.base import ToolContext

    calls = []

    async def fake_enqueue(repo_id, **kwargs):
        calls.append((repo_id, kwargs))
        return "job-1"

    monkeypatch.setattr(jobs_service, "enqueue_index", fake_enqueue)
    ctx = ToolContext(user=USER, repo_ids=["repo-1"], permission_mode="auto")

    applied = {"ok": True, "output": {"staged": False}}
    assert await loop_mod._reindex_after_edit("edit_file", {}, applied, ctx, 1)
    assert calls == [("repo-1", {"reindex": True, "user_id": 1})]

    calls.clear()
    staged = {"ok": True, "output": {"staged": True}}
    assert not await loop_mod._reindex_after_edit("edit_file", {}, staged, ctx, 1)
    assert not await loop_mod._reindex_after_edit("json_tool", {}, applied, ctx, 1)
    assert calls == []


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


@pytest.mark.asyncio
async def test_tool_result_is_truncated_in_llm_messages(monkeypatch):
    class CapturingLLM(FakeLLM):
        def __init__(self, scripts):
            super().__init__(scripts)
            self.seen: list[list[dict]] = []

        async def astream_with_tools(self, messages, tools):
            self.seen.append([dict(message) for message in messages])
            async for event in super().astream_with_tools(messages, tools):
                yield event

    class HugeRegistry:
        def specs(self, **_kwargs):
            return []

        async def execute(self, name, args, ctx):
            return {
                "ok": True,
                "output": {
                    "stdout": "A" * 30_000 + "END",
                    "stderr": "",
                    "exit_code": 1,
                    "command": "pytest",
                },
                "ms": 1,
                "business": False,
            }

    llm = CapturingLLM([
        [
            {"type": "tool_calls", "tool_calls": [
                {"id": "t1", "name": "run_command", "arguments": json.dumps({"command": "pytest"})}
            ]},
            {"type": "finish", "finish_reason": "tool_calls"},
        ],
        [
            {"type": "content", "content": "完成"},
            {"type": "finish", "finish_reason": "stop"},
        ],
    ])
    _patch_common(monkeypatch, llm)
    monkeypatch.setattr(loop_mod, "get_registry", lambda: HugeRegistry())

    await _collect(loop_mod.run_chat(USER, SESSION, "跑测试", []))

    second_round = llm.seen[1]
    tool_message = second_round[-1]
    assert tool_message["role"] == "tool"
    assert "_truncated" in tool_message["content"]
    assert "END" in tool_message["content"]


@pytest.mark.asyncio
async def test_readonly_tools_run_in_parallel(monkeypatch):
    from types import SimpleNamespace

    order: list[str] = []

    class ParallelRegistry:
        def specs(self, **_kwargs):
            return []

        def get(self, name):
            if name == "read_file":
                return SimpleNamespace(parallel_safe=True)
            return None

        async def execute(self, name, args, ctx):
            order.append(f"start:{args['path']}")
            await asyncio.sleep(0.15)
            order.append(f"end:{args['path']}")
            return {
                "ok": True, "output": {"path": args["path"], "content": "x"}, "ms": 150,
            }

    llm = FakeLLM([
        [
            {"type": "tool_calls", "tool_calls": [
                {"id": "t1", "name": "read_file", "arguments": json.dumps({"path": "a.py"})},
                {"id": "t2", "name": "read_file", "arguments": json.dumps({"path": "b.py"})},
            ]},
            {"type": "finish", "finish_reason": "tool_calls"},
        ],
        [
            {"type": "content", "content": "done"},
            {"type": "finish", "finish_reason": "stop"},
        ],
    ])
    _patch_common(monkeypatch, llm)
    monkeypatch.setattr(loop_mod, "get_registry", lambda: ParallelRegistry())
    monkeypatch.setattr(loop_mod, "trace_record", AsyncMock())

    events = await _collect(loop_mod.run_chat(USER, SESSION, "读两个文件", []))

    assert order.index("start:b.py") < order.index("end:a.py")
    results = [e for e in events if e["event"] == "tool_result"]
    assert [e["data"]["name"] for e in results] == ["read_file", "read_file"]
    assert [e["data"]["id"] for e in results] == ["t1", "t2"]


@pytest.mark.asyncio
async def test_update_plan_emits_and_persists(monkeypatch):
    plan_args = json.dumps({
        "steps": [
            {"title": "定位代码", "status": "completed"},
            {"title": "修改实现", "status": "in_progress"},
        ],
        "explanation": "先读后改",
    })
    llm = FakeLLM([
        [
            {"type": "tool_calls", "tool_calls": [
                {"id": "p1", "name": "update_plan", "arguments": plan_args}
            ]},
            {"type": "finish", "finish_reason": "tool_calls"},
        ],
        [
            {"type": "content", "content": "继续执行"},
            {"type": "finish", "finish_reason": "stop"},
        ],
    ])
    _patch_common(monkeypatch, llm)

    events = await _collect(loop_mod.run_chat(USER, SESSION, "做个多步任务", []))

    plan_events = [e for e in events if e["event"] == "plan"]
    assert plan_events and plan_events[0]["data"]["steps"][1]["status"] == "in_progress"
    tool_json = loop_mod.session_mod.add_message.await_args.kwargs["tool_json"]
    assert tool_json["plan"]["explanation"] == "先读后改"
    assert len(tool_json["plan"]["steps"]) == 2


@pytest.mark.asyncio
async def test_tool_output_streams_while_running(monkeypatch):
    class StreamingRegistry:
        def specs(self, **_kwargs):
            return []

        def get(self, name):
            return None

        async def execute(self, name, args, ctx):
            if ctx.output_queue is not None:
                ctx.output_queue.put_nowait(("stdout", "line-1\n"))
            await asyncio.sleep(0.05)
            return {
                "ok": True,
                "output": {"stdout": "line-1\n", "stderr": "", "exit_code": 0,
                           "command": args.get("command", "")},
                "ms": 50,
            }

    llm = FakeLLM([
        [
            {"type": "tool_calls", "tool_calls": [
                {"id": "c1", "name": "run_command", "arguments": json.dumps({"command": "echo hi"})}
            ]},
            {"type": "finish", "finish_reason": "tool_calls"},
        ],
        [
            {"type": "content", "content": "done"},
            {"type": "finish", "finish_reason": "stop"},
        ],
    ])
    _patch_common(monkeypatch, llm)
    monkeypatch.setattr(loop_mod, "get_registry", lambda: StreamingRegistry())

    events = await _collect(loop_mod.run_chat(USER, SESSION, "跑命令", []))

    outputs = [e for e in events if e["event"] == "tool_output"]
    assert outputs and outputs[0]["data"]["text"] == "line-1\n"
    assert outputs[0]["data"]["id"] == "c1"


@pytest.mark.asyncio
async def test_ask_command_approval_pauses_then_runs(monkeypatch):
    from app.core import approvals

    class ApprovalRegistry:
        def specs(self, **_kwargs):
            return []

        def get(self, name):
            return None

        async def execute(self, name, args, ctx):
            if not ctx.approval_granted:
                return {
                    "ok": False, "error": "需要批准", "ms": 0, "business": True,
                    "error_class": "policy",
                    "requires_approval": {
                        "name": name, "args": args, "reason": "需要你批准",
                    },
                }
            return {
                "ok": True,
                "output": {"command": args.get("command"), "exit_code": 0,
                           "stdout": "ok", "stderr": ""},
                "ms": 1,
            }

    llm = FakeLLM([
        [
            {"type": "tool_calls", "tool_calls": [
                {"id": "ap1", "name": "run_command",
                 "arguments": json.dumps({"command": "pytest -q"})}
            ]},
            {"type": "finish", "finish_reason": "tool_calls"},
        ],
        [
            {"type": "content", "content": "执行完成"},
            {"type": "finish", "finish_reason": "stop"},
        ],
    ])
    _patch_common(monkeypatch, llm)
    monkeypatch.setattr(loop_mod, "get_registry", lambda: ApprovalRegistry())

    events = []
    async for event in loop_mod.run_chat(USER, SESSION, "跑测试", []):
        events.append(event)
        if event["event"] == "tool_approval":
            assert event["data"]["args"]["command"] == "pytest -q"
            assert approvals.resolve(SESSION["id"], "ap1", USER["id"], True)

    result = next(e for e in events if e["event"] == "tool_result")
    assert result["data"]["ok"] is True
    approvals.drop(SESSION["id"], "ap1")


@pytest.mark.asyncio
async def test_ask_command_approval_rejection_is_reported(monkeypatch):
    from app.core import approvals

    class ApprovalRegistry:
        def specs(self, **_kwargs):
            return []

        def get(self, name):
            return None

        async def execute(self, name, args, ctx):
            return {
                "ok": False, "error": "需要批准", "ms": 0, "business": True,
                "error_class": "policy",
                "requires_approval": {"name": name, "args": args, "reason": "需要你批准"},
            }

    llm = FakeLLM([
        [
            {"type": "tool_calls", "tool_calls": [
                {"id": "ap2", "name": "run_command",
                 "arguments": json.dumps({"command": "pytest -q"})}
            ]},
            {"type": "finish", "finish_reason": "tool_calls"},
        ],
        [
            {"type": "content", "content": "好"},
            {"type": "finish", "finish_reason": "stop"},
        ],
    ])
    _patch_common(monkeypatch, llm)
    monkeypatch.setattr(loop_mod, "get_registry", lambda: ApprovalRegistry())

    events = []
    async for event in loop_mod.run_chat(USER, SESSION, "跑测试", []):
        events.append(event)
        if event["event"] == "tool_approval":
            assert approvals.resolve(SESSION["id"], "ap2", USER["id"], False)

    result = next(e for e in events if e["event"] == "tool_result")
    assert result["data"]["ok"] is False
    approvals.drop(SESSION["id"], "ap2")

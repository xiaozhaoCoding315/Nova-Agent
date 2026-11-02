"""spawn_agents tool: validation, repo scope, concurrency, events."""
import asyncio
import json

import pytest

from app.core.tools import base as base_mod
from app.core.tools import subagents
from app.core.tools.base import ToolBusinessError, ToolContext

USER = {"id": 1, "username": "admin", "role": "admin"}


def _ctx(**kwargs):
    return ToolContext(
        user=USER, repo_ids=["r1"], session_id="s1", turn_id="t1",
        model="fake-model", llm_overrides={"temperature": 0.2}, **kwargs,
    )


def _ok(kwargs, status="ok"):
    return {
        "id": kwargs["task_id"], "title": kwargs["title"], "status": status,
        "summary": "结论", "findings": [], "files": [], "rounds": 1,
        "tools": ["grep"], "tokens": {"prompt": 1, "completion": 1}, "ms": 5,
        "citations": {"verified": 0, "missing": 0, "out_of_range": 0, "skipped": 0, "executed": False},
        "error": None,
    }


@pytest.fixture(autouse=True)
def _repo(monkeypatch):
    async def fake_get_repo(repo_id, user_id):
        return {"id": repo_id, "name": "repo", "root_path": "C:/repo", "rules": ""}

    monkeypatch.setattr(subagents, "get_repo", fake_get_repo)


@pytest.mark.asyncio
async def test_spawn_agents_normalizes_and_runs(monkeypatch):
    calls = []

    async def fake_run(**kwargs):
        calls.append(kwargs)
        return _ok(kwargs)

    monkeypatch.setattr(subagents, "run_subagent", fake_run)
    ctx = _ctx()
    result = await subagents.spawn_agents({
        "tasks": [
            {"title": "A", "prompt": "prompt A 12345"},
            {"title": "B", "prompt": "prompt B 12345"},
        ],
    }, ctx)

    assert len(calls) == 2
    assert ctx.subagent_tasks_used == 2
    assert result["total"] == 2
    assert result["ok_count"] == 2
    assert all(call["repo_ids"] == ["r1"] for call in calls)
    assert calls[0]["model"] == "fake-model"
    assert calls[0]["overrides"] == {"temperature": 0.2}
    assert calls[0]["repo_roots"] == {"r1": "C:/repo"}


@pytest.mark.asyncio
async def test_spawn_agents_rejects_repo_outside_scope():
    with pytest.raises(ToolBusinessError):
        await subagents.spawn_agents({
            "tasks": [{"title": "A", "prompt": "prompt A 12345", "repo_id": "r2"}],
        }, _ctx())


@pytest.mark.asyncio
async def test_spawn_agents_enforces_turn_limit():
    with pytest.raises(ToolBusinessError):
        await subagents.spawn_agents({
            "tasks": [
                {"title": "A", "prompt": "prompt A 12345"},
                {"title": "B", "prompt": "prompt B 12345"},
            ],
        }, _ctx(subagent_tasks_used=7))


@pytest.mark.asyncio
async def test_spawn_agents_rejects_nested_agent():
    with pytest.raises(ToolBusinessError):
        await subagents.spawn_agents({
            "tasks": [{"title": "A", "prompt": "prompt A 12345"}],
        }, _ctx(agent_depth=1))


@pytest.mark.asyncio
async def test_spawn_agents_isolates_task_failure(monkeypatch):
    async def fake_run(**kwargs):
        if kwargs["title"] == "bad":
            raise RuntimeError("boom")
        return _ok(kwargs)

    monkeypatch.setattr(subagents, "run_subagent", fake_run)
    result = await subagents.spawn_agents({
        "tasks": [
            {"title": "bad", "prompt": "prompt bad 12345"},
            {"title": "good", "prompt": "prompt good 12345"},
        ],
    }, _ctx())

    statuses = [item["status"] for item in result["tasks"]]
    assert statuses == ["failed", "ok"]
    assert result["ok_count"] == 1


@pytest.mark.asyncio
async def test_spawn_agents_emits_subagent_events(monkeypatch):
    queue = asyncio.Queue()

    async def fake_run(**kwargs):
        await kwargs["emit"]({"phase": "start", "id": kwargs["task_id"], "title": kwargs["title"]})
        return _ok(kwargs)

    monkeypatch.setattr(subagents, "run_subagent", fake_run)
    ctx = _ctx()
    ctx.output_queue = queue
    await subagents.spawn_agents({
        "tasks": [{"title": "A", "prompt": "prompt A 12345"}],
    }, ctx)

    stream, text = queue.get_nowait()
    assert stream == "subagent"
    assert json.loads(text)["phase"] == "start"


def test_spawn_agents_tool_definition_and_registration():
    from app.core.tools import get_registry

    assert subagents.TOOL.streaming is True
    assert subagents.TOOL.parallel_safe is False
    assert get_registry().get("spawn_agents") is subagents.TOOL
    assert base_mod.ToolDefinition(name="x", description="", parameters={}, func=None).streaming is False

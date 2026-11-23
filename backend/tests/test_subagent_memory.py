"""Sub-agent role memory: isolated scope, prompt injection and writes."""
from unittest.mock import AsyncMock

import pytest

from app.core.memory import facts as facts_mod
from app.core.memory import policy as policy_mod
from app.core.memory import scope as scope_mod
from app.core.tools import memory_tools
from app.core.tools.base import ToolBusinessError, ToolContext

USER = {"id": 7}


def _ctx(**overrides):
    base = dict(
        user=USER, repo_ids=[], session_id="s1", product_mode="dev",
        thesis_project_id=None,
    )
    base.update(overrides)
    return ToolContext(**base)


@pytest.mark.asyncio
async def test_memory_save_writes_current_scope(monkeypatch):
    monkeypatch.setattr(
        memory_tools.policy_mod, "get_policy",
        AsyncMock(return_value=policy_mod.DEFAULT_POLICY),
    )
    add = AsyncMock(return_value=True)
    monkeypatch.setattr(memory_tools.facts_mod, "add_fact", add)

    result = await memory_tools.memory_save(
        {"content": "以后回答先给结论", "category": "preference"}, _ctx(),
    )

    assert result["saved"] is True
    assert result["pending"] is False
    kwargs = add.await_args.kwargs
    assert kwargs["scope_type"] == scope_mod.DEV
    assert kwargs["explicit"] is True
    assert kwargs["status"] == facts_mod.STATUS_ACTIVE


@pytest.mark.asyncio
async def test_memory_save_rejects_unreadable_scope(monkeypatch):
    monkeypatch.setattr(
        memory_tools.policy_mod, "get_policy",
        AsyncMock(return_value=policy_mod.DEFAULT_POLICY),
    )

    with pytest.raises(ToolBusinessError, match="可写范围"):
        await memory_tools.memory_save(
            {"content": "这个仓库使用 FastAPI", "scope_type": "repo", "scope_id": "r2"},
            _ctx(repo_ids=["r1"]),
        )


@pytest.mark.asyncio
async def test_memory_save_high_risk_goes_to_review(monkeypatch):
    monkeypatch.setattr(
        memory_tools.policy_mod, "get_policy",
        AsyncMock(return_value=policy_mod.DEFAULT_POLICY),
    )
    add = AsyncMock(return_value=True)
    monkeypatch.setattr(memory_tools.facts_mod, "add_fact", add)

    result = await memory_tools.memory_save(
        {"content": "生产数据库密码放在 .env", "category": "fact"}, _ctx(),
    )

    assert result["pending"] is True
    assert add.await_args.kwargs["status"] == facts_mod.STATUS_PENDING
    assert "密钥凭据" in add.await_args.kwargs["risk_reason"]


@pytest.mark.asyncio
async def test_agent_memory_save_forces_agent_scope(monkeypatch):
    monkeypatch.setattr(
        memory_tools.policy_mod, "get_policy",
        AsyncMock(return_value=policy_mod.DEFAULT_POLICY),
    )
    add = AsyncMock(return_value=True)
    monkeypatch.setattr(memory_tools.facts_mod, "add_fact", add)

    result = await memory_tools.agent_memory_save(
        {"content": "评审时优先检查异常路径"}, _ctx(agent_name="review"),
    )

    assert result["scope"] == "agent:review"
    kwargs = add.await_args.kwargs
    assert kwargs["scope_type"] == scope_mod.AGENT
    assert kwargs["scope_id"] == "review"


@pytest.mark.asyncio
async def test_agent_memory_save_requires_agent_context():
    with pytest.raises(ToolBusinessError, match="子代理"):
        await memory_tools.agent_memory_save(
            {"content": "评审时优先检查异常路径"}, _ctx(),
        )


@pytest.mark.asyncio
async def test_agent_read_scope_does_not_include_shared_memory(monkeypatch):
    monkeypatch.setattr(
        memory_tools.facts_mod, "read_fact",
        AsyncMock(return_value={
            "fact": {"scope_type": "global", "scope_id": "", "content": "共享"},
            "sources": {},
        }),
    )
    monkeypatch.setattr(
        memory_tools.policy_mod, "get_policy",
        AsyncMock(return_value=policy_mod.DEFAULT_POLICY),
    )

    with pytest.raises(ToolBusinessError, match="可读范围"):
        await memory_tools.memory_read({"fact_id": 1}, _ctx(agent_name="review"))


@pytest.mark.asyncio
async def test_subagent_prompt_injects_only_its_agent_memory(monkeypatch):
    from app.core.agent import subagent as subagent_mod

    class FakeLLM:
        supports_tools = True
        model = "fake-model"
        context_window = 100_000

        async def astream_with_tools(self, messages, tools):
            self.messages = messages
            yield {"type": "content", "content": "## 结论\n完成"}

        async def astream(self, messages):
            yield "完成"

    class Registry:
        def specs(self, **kwargs):
            return [
                {"type": "function", "function": {
                    "name": "read_file", "description": "", "parameters": {},
                }},
                {"type": "function", "function": {
                    "name": "agent_memory_save", "description": "", "parameters": {},
                }},
            ]

        async def execute(self, name, args, ctx):
            return {"ok": True, "output": {}, "ms": 1, "business": False}

    llm = FakeLLM()
    monkeypatch.setattr(subagent_mod, "get_llm", AsyncMock(return_value=llm))
    monkeypatch.setattr(subagent_mod, "ensure_token_budget", AsyncMock())
    monkeypatch.setattr(subagent_mod, "record_usage", AsyncMock())
    monkeypatch.setattr(subagent_mod, "trace_record", AsyncMock())
    monkeypatch.setattr(
        subagent_mod, "verify_citations",
        AsyncMock(return_value={
            "citations": [], "executed": False, "verified": 0,
            "missing": 0, "out_of_range": 0, "skipped": 0,
        }),
    )
    get_facts = AsyncMock(return_value=[
        (3, "评审时优先检查异常路径", "preference"),
        (4, "工资是 12345", "fact"),
    ])
    monkeypatch.setattr(subagent_mod.facts_mod, "get_relevant_facts", get_facts)
    monkeypatch.setattr(
        subagent_mod.memory_policy_mod, "get_policy",
        AsyncMock(return_value=policy_mod.MemoryPolicy(blocked_keywords=("工资",))),
    )

    result = await subagent_mod.run_subagent(
        user=USER, session_id="s1", turn_id="t1", task_id="sa-1",
        title="评审", prompt="评审鉴权中间件并给出文件行号", repo_ids=["r1"],
        repos=[{"id": "r1", "name": "repo", "rules": ""}],
        repo_roots={"r1": "C:/repo"}, registry=Registry(), agent_name="review",
    )

    system = llm.messages[0]["content"]
    assert "子代理记忆" in system
    assert "异常路径" in system
    assert "工资" not in system
    assert get_facts.await_args.kwargs["scopes"] == [
        scope_mod.Scope(scope_mod.AGENT, "review")
    ]
    assert result["agent"] == "review"


@pytest.mark.asyncio
async def test_spawn_agents_passes_agent_role(monkeypatch):
    from app.core.tools import subagents

    calls = []

    async def fake_run(**kwargs):
        calls.append(kwargs)
        return {
            "id": kwargs["task_id"], "title": kwargs["title"], "status": "ok",
            "summary": "s", "findings": [], "files": [], "rounds": 1,
            "tools": [], "tokens": {"prompt": 0, "completion": 0}, "ms": 0,
            "citations": {}, "error": None, "agent": kwargs.get("agent_name", ""),
        }

    async def fake_repo(repo_id, user_id):
        return {"id": repo_id, "name": "repo", "root_path": "", "rules": ""}

    monkeypatch.setattr(subagents, "run_subagent", fake_run)
    monkeypatch.setattr(subagents, "get_repo", fake_repo)
    monkeypatch.setattr(
        subagents.instructions_mod, "for_turn",
        AsyncMock(return_value=([], [])),
    )

    await subagents.spawn_agents({
        "tasks": [{
            "title": "评审", "prompt": "评审鉴权中间件并给出文件行号",
            "agent": "review",
        }],
    }, _ctx(repo_ids=["r1"]))

    assert calls[0]["agent_name"] == "review"


@pytest.mark.asyncio
async def test_spawn_agents_rejects_invalid_agent_role(monkeypatch):
    from app.core.tools import subagents

    monkeypatch.setattr(
        subagents.instructions_mod, "for_turn",
        AsyncMock(return_value=([], [])),
    )

    with pytest.raises(ToolBusinessError, match="agent"):
        await subagents.spawn_agents({
            "tasks": [{
                "title": "评审", "prompt": "评审鉴权中间件并给出文件行号",
                "agent": "Bad Role!",
            }],
        }, _ctx(repo_ids=["r1"]))

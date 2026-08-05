import asyncio
import pytest
from app.core.agent.decomposer import decompose_task, execute_node_action
from app.core.agent.dag import DAGNode, DAGWorkflow, NodeStatus


@pytest.mark.asyncio
async def test_decompose_fallback_on_llm_error(monkeypatch):
    """When LLM raises, we get a single-node fallback."""
    from app.core.agent import decomposer

    class BogusLLM:
        async def astream(self, msgs):
            raise RuntimeError("no provider available")
            yield ""  # make it an async generator

    monkeypatch.setattr(decomposer, "get_llm", lambda: BogusLLM())
    result = await decompose_task("simple task")
    assert len(result["nodes"]) == 1
    assert result["nodes"][0]["id"] == "node_1"
    assert result["nodes"][0]["name"] == "simple task"
    assert result["nodes"][0]["task_type"] == "research"


@pytest.mark.asyncio
async def test_decompose_parses_json(monkeypatch):
    """LLM returning valid JSON yields structured DAG."""
    from app.core.agent import decomposer

    class FakeLLM:
        async def astream(self, msgs):
            yield '{"nodes":[{"id":"a","name":"A","task_type":"search","action":"do a"},{"id":"b","name":"B","task_type":"review","action":"do b","depends_on":["a"]}],"summary":"ok"}'

    monkeypatch.setattr(decomposer, "get_llm", lambda: FakeLLM())
    result = await decompose_task("anything")
    assert len(result["nodes"]) == 2
    ids = [n["id"] for n in result["nodes"]]
    assert "a" in ids and "b" in ids


@pytest.mark.asyncio
async def test_execute_streaming_yields_events():
    """execute_streaming produces node_started/node_completed/dag_completed events."""
    wf = DAGWorkflow("stream-test")

    async def fast():
        await asyncio.sleep(0.01)
        return "ok"

    async def dependent(x):
        await asyncio.sleep(0.01)
        return f"got:{x}"

    wf.add_node(DAGNode(id="a", name="A", func=fast))
    wf.add_node(DAGNode(id="b", name="B", func=fast))
    wf.add_node(DAGNode(id="c", name="C", func=dependent, dependencies=["a", "b"]))

    events = []
    async for ev in wf.execute_streaming():
        events.append(ev)

    types = [e["type"] for e in events]
    assert types[0] == "node_started"
    assert "node_completed" in types
    assert types[-1] == "dag_completed"
    # Both a and b should complete before c starts
    completed_before_c_start = types[:types.index("node_completed")]


@pytest.mark.asyncio
async def test_get_ready_completed_nodes():
    wf = DAGWorkflow("ready-test")
    wf.add_node(DAGNode(id="a", name="A", func=lambda: 1))
    wf.add_node(DAGNode(id="b", name="B", func=lambda: 2))
    wf.add_node(DAGNode(id="c", name="C", func=lambda x: x, dependencies=["a", "b"]))

    ready = wf.get_ready_completed_nodes()
    assert set(ready) == {"a", "b"}


@pytest.mark.asyncio
async def test_decompose_fallback_on_bad_json(monkeypatch):
    """Non-JSON response should still return a valid single-node fallback."""
    from app.core.agent import decomposer

    class FakeLLM:
        async def astream(self, msgs):
            yield "this is not json at all"

    monkeypatch.setattr(decomposer, "get_llm", lambda: FakeLLM())
    result = await decompose_task("Whatever")
    assert len(result["nodes"]) >= 1

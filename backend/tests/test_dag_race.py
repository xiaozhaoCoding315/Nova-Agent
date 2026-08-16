import asyncio, pytest
from app.core.agent.dag import DAGWorkflow, DAGNode

async def mock_work(val):
    await asyncio.sleep(0.01)
    return f"result_{val}"

@pytest.mark.asyncio
async def test_execute_race_streaming_completes():
    wf = DAGWorkflow("race-test")
    wf.add_node(DAGNode(id="a", name="A", func=mock_work, args=("a",)))
    wf.add_node(DAGNode(id="b", name="B", func=mock_work, args=("b",)))
    events = []
    async for event in wf.execute_race_streaming():
        events.append(event)
    types = [e["type"] for e in events]
    assert "dag_completed" in types
    completed = [e for e in events if e["type"] == "node_completed"]
    assert len(completed) == 2

@pytest.mark.asyncio
async def test_race_mode_attribute():
    wf = DAGWorkflow("race-attr-test")
    assert hasattr(wf, "execute_race_streaming")

@pytest.mark.asyncio
async def test_race_streaming_slow_sibling_not_cancelled():
    """Sibling nodes with different speeds must BOTH complete (no mutual cancel)."""
    async def fast():
        await asyncio.sleep(0.01)
        return "fast_done"

    async def slow():
        await asyncio.sleep(0.15)
        return "slow_done"

    wf = DAGWorkflow("race-fix")
    wf.add_node(DAGNode(id="a", name="A", func=fast))
    wf.add_node(DAGNode(id="b", name="B", func=slow))
    events = []
    async for event in wf.execute_race_streaming():
        events.append(event)
    completed = [e for e in events if e["type"] == "node_completed"]
    failed = [e for e in events if e["type"] == "node_failed"]
    assert len(completed) == 2, f"expected both siblings to complete, got {completed} {failed}"

@pytest.mark.asyncio
async def test_dag_completed_includes_results():
    async def work():
        return {"answer": 42}

    wf = DAGWorkflow("r")
    wf.add_node(DAGNode(id="a", name="A", func=work))
    events = [e async for e in wf.execute_race_streaming()]
    done = events[-1]
    assert done["type"] == "dag_completed"
    assert done["results"] == {"a": {"answer": 42}}

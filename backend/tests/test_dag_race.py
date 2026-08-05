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

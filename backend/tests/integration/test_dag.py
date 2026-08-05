import pytest, asyncio
from app.core.agent.dag import DAGWorkflow, DAGNode

async def mock_work(x):
    await asyncio.sleep(0.01)
    return f"result_{x}"

@pytest.mark.asyncio
@pytest.mark.integration
async def test_dag_race_execution():
    wf = DAGWorkflow("integration-race")
    wf.add_node(DAGNode(id="a", name="A", func=mock_work, args=("a",)))
    wf.add_node(DAGNode(id="b", name="B", func=mock_work, args=("b",)))
    events = []
    async for e in wf.execute_race_streaming():
        events.append(e)
    assert any(e["type"] == "dag_completed" for e in events)

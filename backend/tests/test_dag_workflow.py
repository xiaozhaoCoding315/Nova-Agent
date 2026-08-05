import asyncio
import pytest
from app.core.agent.dag import DAGNode, DAGWorkflow, NodeStatus


async def dummy_task(x, add=0):
    await asyncio.sleep(0.01)
    return x + add


async def failing_task():
    await asyncio.sleep(0.01)
    raise RuntimeError("boom")


@pytest.mark.asyncio
async def test_simple_linear_dag():
    wf = DAGWorkflow("linear")
    wf.add_node(DAGNode(id="a", name="A", func=dummy_task, args=(1,)))
    wf.add_node(DAGNode(id="b", name="B", func=dummy_task, args=(2,), dependencies=["a"]))
    wf.add_node(DAGNode(id="c", name="C", func=dummy_task, args=(3,), dependencies=["b"]))

    results = await wf.execute()
    assert results["a"].status == NodeStatus.COMPLETED
    assert results["b"].status == NodeStatus.COMPLETED
    assert results["c"].status == NodeStatus.COMPLETED
    assert results["a"].result == 1
    assert results["b"].result == 2
    assert results["c"].result == 3


@pytest.mark.asyncio
async def test_parallel_execution():
    """Independent nodes should run in parallel (total time ~0.05s not 0.15s)."""
    wf = DAGWorkflow("parallel")

    async def slow_task():
        await asyncio.sleep(0.05)
        return "done"

    wf.add_node(DAGNode(id="a", name="A", func=slow_task))
    wf.add_node(DAGNode(id="b", name="B", func=slow_task))
    wf.add_node(DAGNode(id="c", name="C", func=slow_task))

    start = asyncio.get_event_loop().time()
    results = await wf.execute()
    elapsed = asyncio.get_event_loop().time() - start

    assert results["a"].result == "done"
    assert results["b"].result == "done"
    assert results["c"].result == "done"
    # If truly parallel, should be ~0.05s, not 0.15s
    assert elapsed < 0.15


@pytest.mark.asyncio
async def test_dependency_failure_skips_children():
    wf = DAGWorkflow("fail-skip")
    wf.add_node(DAGNode(id="a", name="A", func=failing_task, max_retries=0))
    wf.add_node(DAGNode(id="b", name="B", func=dummy_task, args=(1,), dependencies=["a"]))

    results = await wf.execute()
    assert results["a"].status == NodeStatus.FAILED
    assert results["b"].status == NodeStatus.SKIPPED
    assert "a" in (results["b"].error or "")


@pytest.mark.asyncio
async def test_retry_on_failure():
    call_count = 0

    async def flaky():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise RuntimeError("not yet")
        return "success"

    wf = DAGWorkflow("retry")
    wf.add_node(DAGNode(id="a", name="A", func=flaky, max_retries=3))

    results = await wf.execute()
    assert results["a"].status == NodeStatus.COMPLETED
    assert results["a"].result == "success"
    assert call_count == 3


@pytest.mark.asyncio
async def test_cycle_detection():
    wf = DAGWorkflow("cycle")
    wf.add_node(DAGNode(id="a", name="A", func=dummy_task, args=(1,), dependencies=["b"]))
    wf.add_node(DAGNode(id="b", name="B", func=dummy_task, args=(2,), dependencies=["a"]))

    with pytest.raises(ValueError, match="Cycle"):
        await wf.execute()


@pytest.mark.asyncio
async def test_missing_dependency():
    wf = DAGWorkflow("missing")
    wf.add_node(DAGNode(id="a", name="A", func=dummy_task, args=(1,), dependencies=["nonexistent"]))

    with pytest.raises(ValueError, match="unknown node"):
        await wf.execute()


@pytest.mark.asyncio
async def test_duplicate_node_id():
    wf = DAGWorkflow("dup")
    wf.add_node(DAGNode(id="a", name="A", func=dummy_task, args=(1,)))
    with pytest.raises(ValueError, match="Duplicate"):
        wf.add_node(DAGNode(id="a", name="A2", func=dummy_task, args=(2,)))


@pytest.mark.asyncio
async def test_get_status_summary():
    wf = DAGWorkflow("summary")
    wf.add_node(DAGNode(id="a", name="A", func=dummy_task, args=(1,)))
    wf.add_node(DAGNode(id="b", name="B", func=failing_task, max_retries=0))

    await wf.execute()
    status = wf.get_status()
    assert status["total_nodes"] == 2
    assert status["status_counts"]["completed"] == 1
    assert status["status_counts"]["failed"] == 1


@pytest.mark.asyncio
async def test_diamond_dependency():
    """Diamond: A -> B, A -> C, B&D -> D"""
    wf = DAGWorkflow("diamond")
    wf.add_node(DAGNode(id="a", name="A", func=dummy_task, args=(10,)))
    wf.add_node(DAGNode(id="b", name="B", func=dummy_task, args=(1,), dependencies=["a"]))
    wf.add_node(DAGNode(id="c", name="C", func=dummy_task, args=(2,), dependencies=["a"]))
    wf.add_node(
        DAGNode(id="d", name="D", func=lambda x, y: x + y, dependencies=["b", "c"])
    )

    results = await wf.execute()
    assert results["a"].status == NodeStatus.COMPLETED
    assert results["b"].status == NodeStatus.COMPLETED
    assert results["c"].status == NodeStatus.COMPLETED
    assert results["d"].status == NodeStatus.COMPLETED

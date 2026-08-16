import uuid
import pytest
from app.core.agent.task_store import TaskStore


@pytest.mark.asyncio
@pytest.mark.integration
async def test_save_and_get():
    tid = f"ts-{uuid.uuid4().hex[:8]}"
    await TaskStore.save({
        "id": tid, "name": "测试任务", "status": "completed",
        "result": {"answer": 42}, "error": None,
        "created_at": "2026-08-11T00:00:00", "started_at": None,
        "completed_at": "2026-08-11T00:00:01", "retries": 0, "max_retries": 2,
        "parent_id": None, "children_ids": [], "metadata": {"k": "v"},
        "history": [{"event": "created", "message": "hi", "timestamp": "t"}],
    })
    got = await TaskStore.get(tid)
    assert got is not None
    assert got["name"] == "测试任务"
    assert got["status"] == "completed"
    assert got["result"] == {"answer": 42}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_filters_by_status():
    await TaskStore.clear()
    await TaskStore.save({"id": "l1", "name": "a", "status": "running", "result": None,
                          "error": None, "created_at": "2026-08-11T00:00:00",
                          "started_at": None, "completed_at": None, "retries": 0,
                          "max_retries": 2, "parent_id": None, "children_ids": [],
                          "metadata": {}, "history": []})
    await TaskStore.save({"id": "l2", "name": "b", "status": "completed", "result": None,
                          "error": None, "created_at": "2026-08-11T00:00:01",
                          "started_at": None, "completed_at": None, "retries": 0,
                          "max_retries": 2, "parent_id": None, "children_ids": [],
                          "metadata": {}, "history": []})
    running = await TaskStore.list(status="running")
    assert any(t["id"] == "l1" for t in running)
    assert not any(t["id"] == "l2" for t in running)

import pytest
from app.core.agent.state import TaskStateManager, TaskStatus


def test_create_task():
    mgr = TaskStateManager()
    task = mgr.create_task(name="test-task")
    assert task.status == TaskStatus.PENDING
    assert task.name == "test-task"
    assert len(task.id) > 0


def test_task_lifecycle():
    mgr = TaskStateManager()
    task = mgr.create_task(name="lifecycle-task")

    mgr.start_task(task.id)
    assert task.status == TaskStatus.RUNNING
    assert task.started_at is not None

    mgr.complete_task(task.id, result="done")
    assert task.status == TaskStatus.COMPLETED
    assert task.result == "done"
    assert task.completed_at is not None
    assert task.elapsed_ms is not None


def test_task_failure_with_retries():
    mgr = TaskStateManager()
    task = mgr.create_task(name="retry-task", max_retries=2)

    mgr.start_task(task.id)
    mgr.fail_task(task.id, error="first failure")
    assert task.status == TaskStatus.PENDING  # retryable
    assert task.retries == 1

    mgr.start_task(task.id)
    mgr.fail_task(task.id, error="second failure")
    assert task.status == TaskStatus.PENDING  # still retryable
    assert task.retries == 2

    mgr.start_task(task.id)
    mgr.fail_task(task.id, error="final failure")
    assert task.status == TaskStatus.FAILED
    assert task.retries == 2
    assert "final failure" in task.error


def test_task_cancel():
    mgr = TaskStateManager()
    task = mgr.create_task(name="cancel-me")
    mgr.start_task(task.id)
    mgr.cancel_task(task.id)
    assert task.status == TaskStatus.CANCELLED


def test_task_skip():
    mgr = TaskStateManager()
    task = mgr.create_task(name="skip-me")
    mgr.skip_task(task.id, reason="dependency failed")
    assert task.status == TaskStatus.SKIPPED
    assert task.error == "dependency failed"


def test_parent_child_relationship():
    mgr = TaskStateManager()
    parent = mgr.create_task(name="parent")
    child1 = mgr.create_task(name="child1", parent_id=parent.id)
    child2 = mgr.create_task(name="child2", parent_id=parent.id)

    assert child1.parent_id == parent.id
    assert child2.parent_id == parent.id
    assert len(parent.children_ids) == 2

    children = mgr.get_children(parent.id)
    assert len(children) == 2


def test_get_task_result():
    mgr = TaskStateManager()
    task = mgr.create_task(name="result-task")
    mgr.start_task(task.id)
    mgr.complete_task(task.id, result={"data": 42})

    assert mgr.get_task_result(task.id) == {"data": 42}


def test_get_summary():
    mgr = TaskStateManager()
    t1 = mgr.create_task(name="a")
    t2 = mgr.create_task(name="b")
    mgr.complete_task(t1.id)

    summary = mgr.get_summary()
    assert summary["total"] == 2
    assert summary["status_counts"]["completed"] == 1
    assert summary["status_counts"]["pending"] == 1


def test_history_tracking():
    mgr = TaskStateManager()
    task = mgr.create_task(name="history-task")
    mgr.start_task(task.id)
    mgr.complete_task(task.id)

    events = [h["event"] for h in task.history]
    assert "created" in events
    assert "started" in events
    assert "completed" in events


def test_clear():
    mgr = TaskStateManager()
    task = mgr.create_task(name="to-clear")
    mgr.complete_task(task.id, result="something")

    mgr.clear()
    assert mgr.get_task(task.id) is None
    assert len(mgr.get_all_tasks()) == 0


def test_get_root_tasks():
    mgr = TaskStateManager()
    root1 = mgr.create_task(name="root1")
    root2 = mgr.create_task(name="root2")
    child = mgr.create_task(name="child", parent_id=root1.id)

    roots = mgr.get_root_tasks()
    root_ids = {t.id for t in roots}
    assert root1.id in root_ids
    assert root2.id in root_ids
    assert child.id not in root_ids


@pytest.mark.asyncio
async def test_persist_writes_to_store():
    import uuid
    from app.core.agent.task_store import TaskStore
    mgr = TaskStateManager()
    tid = f"persist-{uuid.uuid4().hex[:8]}"
    task = mgr.create_task(name="persist-me", task_id=tid)
    mgr.start_task(tid)
    mgr.complete_task(tid, result="ok")
    # _persist fires via running loop; give it a tick
    import asyncio
    await asyncio.sleep(0.05)
    saved = await TaskStore.get(tid)
    assert saved is not None
    assert saved["status"] == "completed"
    assert saved["result"] == "ok"

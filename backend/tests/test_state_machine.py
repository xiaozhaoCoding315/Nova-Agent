"""Tests for the structured state machine (TaskStateMachine)."""
import pytest
from app.core.agent.state_machine import (
    TaskState,
    TaskNode,
    TaskStateMachine,
    VALID_TRANSITIONS,
    StateTransition,
)


# ── TaskState enum ──────────────────────────────────────────────────────────

class TestTaskState:
    def test_enum_values(self):
        assert TaskState.PENDING.value == "pending"
        assert TaskState.RUNNING.value == "running"
        assert TaskState.WAITING.value == "waiting"
        assert TaskState.COMPLETED.value == "completed"
        assert TaskState.FAILED.value == "failed"
        assert TaskState.CANCELLED.value == "cancelled"
        assert TaskState.PAUSED.value == "paused"

    def test_enum_is_str_subclass(self):
        """TaskState values should be comparable to plain strings."""
        assert TaskState.PENDING == "pending"
        assert TaskState.RUNNING == "running"


# ── VALID_TRANSITIONS ──────────────────────────────────────────────────────

class TestValidTransitions:
    def test_pending_targets(self):
        assert set(VALID_TRANSITIONS[TaskState.PENDING]) == {TaskState.RUNNING, TaskState.CANCELLED}

    def test_running_targets(self):
        assert set(VALID_TRANSITIONS[TaskState.RUNNING]) == {
            TaskState.COMPLETED, TaskState.FAILED, TaskState.PAUSED, TaskState.WAITING, TaskState.CANCELLED,
        }

    def test_waiting_targets(self):
        assert set(VALID_TRANSITIONS[TaskState.WAITING]) == {TaskState.RUNNING, TaskState.CANCELLED}

    def test_paused_targets(self):
        assert set(VALID_TRANSITIONS[TaskState.PAUSED]) == {TaskState.RUNNING, TaskState.CANCELLED}

    def test_failed_targets(self):
        assert set(VALID_TRANSITIONS[TaskState.FAILED]) == {TaskState.PENDING}

    def test_completed_is_terminal(self):
        assert VALID_TRANSITIONS[TaskState.COMPLETED] == []

    def test_cancelled_is_terminal(self):
        assert VALID_TRANSITIONS[TaskState.CANCELLED] == []


# ── TaskNode ────────────────────────────────────────────────────────────────

class TestTaskNode:
    def test_creation_defaults(self):
        node = TaskNode(id="abc", name="test")
        assert node.id == "abc"
        assert node.name == "test"
        assert node.state == TaskState.PENDING
        assert node.result is None
        assert node.error is None
        assert node.history == []
        assert node.parent_id is None
        assert node.children == []
        assert node.metadata == {}
        assert isinstance(node.created_at, float)
        assert isinstance(node.updated_at, float)

    def test_creation_with_metadata(self):
        node = TaskNode(id="x", name="y", metadata={"key": "val"})
        assert node.metadata == {"key": "val"}

    def test_valid_transition(self):
        node = TaskNode(id="a", name="task")
        node.transition(TaskState.RUNNING)
        assert node.state == TaskState.RUNNING
        assert len(node.history) == 1
        assert node.history[0].from_state == TaskState.PENDING
        assert node.history[0].to_state == TaskState.RUNNING

    def test_invalid_transition_raises(self):
        node = TaskNode(id="a", name="task")
        with pytest.raises(ValueError, match="Invalid transition"):
            node.transition(TaskState.COMPLETED)

    def test_invalid_transition_error_message(self):
        node = TaskNode(id="a", name="task")
        with pytest.raises(ValueError, match="pending -> completed"):
            node.transition(TaskState.COMPLETED)

    def test_transition_with_reason(self):
        node = TaskNode(id="a", name="task")
        node.transition(TaskState.RUNNING, reason="started by worker")
        assert node.history[0].reason == "started by worker"

    def test_full_lifecycle_transitions(self):
        node = TaskNode(id="a", name="lifecycle")
        node.transition(TaskState.RUNNING)
        node.transition(TaskState.COMPLETED)
        assert node.state == TaskState.COMPLETED
        assert len(node.history) == 2

    def test_running_to_paused_to_running(self):
        node = TaskNode(id="a", name="pause-test")
        node.transition(TaskState.RUNNING)
        node.transition(TaskState.PAUSED)
        assert node.state == TaskState.PAUSED
        node.transition(TaskState.RUNNING)
        assert node.state == TaskState.RUNNING

    def test_running_to_waiting_to_running(self):
        node = TaskNode(id="a", name="wait-test")
        node.transition(TaskState.RUNNING)
        node.transition(TaskState.WAITING, reason="awaiting user input")
        assert node.state == TaskState.WAITING
        node.transition(TaskState.RUNNING)
        assert node.state == TaskState.RUNNING

    def test_failed_to_pending_retry(self):
        node = TaskNode(id="a", name="retry-test")
        node.transition(TaskState.RUNNING)
        node.transition(TaskState.FAILED)
        assert node.state == TaskState.FAILED
        node.transition(TaskState.PENDING, reason="retrying")
        assert node.state == TaskState.PENDING

    def test_terminal_state_no_transitions(self):
        node = TaskNode(id="a", name="terminal")
        node.transition(TaskState.RUNNING)
        node.transition(TaskState.COMPLETED)
        with pytest.raises(ValueError):
            node.transition(TaskState.PENDING)

    def test_transition_updates_timestamp(self):
        node = TaskNode(id="a", name="ts-test")
        old_ts = node.updated_at
        import time
        time.sleep(0.01)
        node.transition(TaskState.RUNNING)
        assert node.updated_at > old_ts

    def test_history_is_audit_trail(self):
        node = TaskNode(id="a", name="audit")
        node.transition(TaskState.RUNNING, reason="begin")
        node.transition(TaskState.WAITING, reason="need input")
        node.transition(TaskState.RUNNING, reason="resumed")
        node.transition(TaskState.COMPLETED, reason="done")

        events = [(h.from_state, h.to_state) for h in node.history]
        assert events == [
            (TaskState.PENDING, TaskState.RUNNING),
            (TaskState.RUNNING, TaskState.WAITING),
            (TaskState.WAITING, TaskState.RUNNING),
            (TaskState.RUNNING, TaskState.COMPLETED),
        ]


# ── TaskStateMachine ─────────────────────────────────────────────────────────

class TestTaskStateMachine:
    def test_creation(self):
        sm = TaskStateMachine(name="test-machine")
        assert sm.name == "test-machine"
        assert len(sm.id) == 8
        assert sm.tasks == {}
        assert sm.root_tasks == []

    def test_add_task_returns_id(self):
        sm = TaskStateMachine(name="m")
        tid = sm.add_task(name="task1")
        assert isinstance(tid, str)
        assert len(tid) == 8
        assert tid in sm.tasks

    def test_add_task_is_root_by_default(self):
        sm = TaskStateMachine(name="m")
        tid = sm.add_task(name="root-task")
        assert tid in sm.root_tasks

    def test_add_child_task(self):
        sm = TaskStateMachine(name="m")
        parent_id = sm.add_task(name="parent")
        child_id = sm.add_task(name="child", parent_id=parent_id)

        assert child_id not in sm.root_tasks
        assert child_id in sm.tasks[parent_id].children
        assert sm.tasks[child_id].parent_id == parent_id

    def test_add_task_with_metadata(self):
        sm = TaskStateMachine(name="m")
        tid = sm.add_task(name="meta", metadata={"priority": "high"})
        assert sm.tasks[tid].metadata == {"priority": "high"}

    def test_add_task_with_unknown_parent_becomes_root(self):
        """If parent_id is not in tasks, the task becomes a root task."""
        sm = TaskStateMachine(name="m")
        tid = sm.add_task(name="orphan", parent_id="nonexistent")
        assert tid in sm.root_tasks

    def test_transition(self):
        sm = TaskStateMachine(name="m")
        tid = sm.add_task(name="t")
        sm.transition(tid, TaskState.RUNNING)
        assert sm.tasks[tid].state == TaskState.RUNNING

    def test_transition_invalid_raises(self):
        sm = TaskStateMachine(name="m")
        tid = sm.add_task(name="t")
        with pytest.raises(ValueError, match="Invalid transition"):
            sm.transition(tid, TaskState.COMPLETED)

    def test_transition_unknown_task_raises(self):
        sm = TaskStateMachine(name="m")
        with pytest.raises(KeyError, match="not found"):
            sm.transition("nonexistent", TaskState.RUNNING)

    def test_set_result(self):
        sm = TaskStateMachine(name="m")
        tid = sm.add_task(name="t")
        sm.set_result(tid, result={"output": 42})
        assert sm.tasks[tid].result == {"output": 42}

    def test_set_error(self):
        sm = TaskStateMachine(name="m")
        tid = sm.add_task(name="t")
        sm.set_error(tid, error="something broke")
        assert sm.tasks[tid].error == "something broke"

    def test_get_task(self):
        sm = TaskStateMachine(name="m")
        tid = sm.add_task(name="t")
        task = sm.get_task(tid)
        assert task is not None
        assert task.id == tid
        assert task.name == "t"

    def test_get_task_missing(self):
        sm = TaskStateMachine(name="m")
        assert sm.get_task("nonexistent") is None


# ── get_ready_tasks ──────────────────────────────────────────────────────────

class TestGetReadyTasks:
    def test_all_pending_roots_are_ready(self):
        sm = TaskStateMachine(name="m")
        t1 = sm.add_task(name="a")
        t2 = sm.add_task(name="b")
        sm.transition(t1, TaskState.RUNNING)
        sm.transition(t1, TaskState.COMPLETED)

        ready = sm.get_ready_tasks()
        assert t2 in ready

    def test_running_tasks_not_ready(self):
        sm = TaskStateMachine(name="m")
        t1 = sm.add_task(name="a")
        sm.transition(t1, TaskState.RUNNING)

        assert t1 not in sm.get_ready_tasks()

    def test_completed_tasks_not_ready(self):
        sm = TaskStateMachine(name="m")
        t1 = sm.add_task(name="a")
        sm.transition(t1, TaskState.RUNNING)
        sm.transition(t1, TaskState.COMPLETED)

        assert t1 not in sm.get_ready_tasks()

    def test_child_not_ready_until_parent_completed(self):
        sm = TaskStateMachine(name="m")
        parent = sm.add_task(name="parent")
        child = sm.add_task(name="child", parent_id=parent)

        # Parent still pending
        assert child not in sm.get_ready_tasks()

        # Parent running
        sm.transition(parent, TaskState.RUNNING)
        assert child not in sm.get_ready_tasks()

        # Parent completed — child should be ready
        sm.transition(parent, TaskState.COMPLETED)
        assert child in sm.get_ready_tasks()

    def test_child_ready_with_no_parent(self):
        """Root tasks with no parent are ready when pending."""
        sm = TaskStateMachine(name="m")
        t1 = sm.add_task(name="root")
        assert t1 in sm.get_ready_tasks()

    def test_multiple_ready_tasks(self):
        sm = TaskStateMachine(name="m")
        t1 = sm.add_task(name="a")
        t2 = sm.add_task(name="b")
        t3 = sm.add_task(name="c")

        ready = sm.get_ready_tasks()
        assert set(ready) == {t1, t2, t3}

    def test_empty_machine_no_ready(self):
        sm = TaskStateMachine(name="m")
        assert sm.get_ready_tasks() == []


# ── get_progress ─────────────────────────────────────────────────────────────

class TestGetProgress:
    def test_empty_progress(self):
        sm = TaskStateMachine(name="m")
        progress = sm.get_progress()
        assert progress["total"] == 0
        assert progress["completed"] == 0
        assert progress["progress_pct"] == 0
        assert progress["by_state"] == {}

    def test_all_pending(self):
        sm = TaskStateMachine(name="m")
        sm.add_task(name="a")
        sm.add_task(name="b")

        progress = sm.get_progress()
        assert progress["total"] == 2
        assert progress["completed"] == 0
        assert progress["progress_pct"] == 0.0
        assert progress["by_state"] == {"pending": 2}

    def test_partial_completion(self):
        sm = TaskStateMachine(name="m")
        t1 = sm.add_task(name="a")
        t2 = sm.add_task(name="b")
        t3 = sm.add_task(name="c")

        sm.transition(t1, TaskState.RUNNING)
        sm.transition(t1, TaskState.COMPLETED)
        sm.transition(t2, TaskState.RUNNING)
        sm.transition(t2, TaskState.FAILED)

        progress = sm.get_progress()
        assert progress["total"] == 3
        assert progress["completed"] == 1
        assert progress["progress_pct"] == 33.3
        assert progress["by_state"]["completed"] == 1
        assert progress["by_state"]["failed"] == 1
        assert progress["by_state"]["pending"] == 1

    def test_all_completed(self):
        sm = TaskStateMachine(name="m")
        t1 = sm.add_task(name="a")
        sm.transition(t1, TaskState.RUNNING)
        sm.transition(t1, TaskState.COMPLETED)

        progress = sm.get_progress()
        assert progress["progress_pct"] == 100.0


# ── to_dict (serialization) ─────────────────────────────────────────────────

class TestToDict:
    def test_basic_structure(self):
        sm = TaskStateMachine(name="viz-test")
        d = sm.to_dict()

        assert d["id"] == sm.id
        assert d["name"] == "viz-test"
        assert "progress" in d
        assert "tasks" in d
        assert "root_tasks" in d

    def test_serialized_task_fields(self):
        sm = TaskStateMachine(name="ser")
        tid = sm.add_task(name="task-a", metadata={"type": "io"})
        sm.transition(tid, TaskState.RUNNING)

        d = sm.to_dict()
        task_dict = d["tasks"][tid]
        assert task_dict["id"] == tid
        assert task_dict["name"] == "task-a"
        assert task_dict["state"] == "running"
        assert task_dict["metadata"] == {"type": "io"}
        assert task_dict["parent_id"] is None
        assert task_dict["children"] == []
        assert len(task_dict["history"]) == 1
        assert task_dict["history"][0]["from"] == "pending"
        assert task_dict["history"][0]["to"] == "running"

    def test_serialized_history_reasons(self):
        sm = TaskStateMachine(name="ser")
        tid = sm.add_task(name="t")
        sm.transition(tid, TaskState.RUNNING, reason="begin work")

        d = sm.to_dict()
        assert d["tasks"][tid]["history"][0]["reason"] == "begin work"

    def test_child_relationship_serialized(self):
        sm = TaskStateMachine(name="ser")
        parent = sm.add_task(name="parent")
        child = sm.add_task(name="child", parent_id=parent)

        d = sm.to_dict()
        assert child in d["tasks"][parent]["children"]
        assert d["tasks"][child]["parent_id"] == parent

    def test_root_tasks_list(self):
        sm = TaskStateMachine(name="ser")
        r1 = sm.add_task(name="r1")
        r2 = sm.add_task(name="r2")
        sm.add_task(name="child", parent_id=r1)

        d = sm.to_dict()
        assert set(d["root_tasks"]) == {r1, r2}

    def test_progress_in_output(self):
        sm = TaskStateMachine(name="ser")
        sm.add_task(name="a")
        d = sm.to_dict()
        assert d["progress"]["total"] == 1
        assert d["progress"]["completed"] == 0


# ── Integration scenarios ────────────────────────────────────────────────────

class TestIntegration:
    def test_linear_three_step_workflow(self):
        """Simulate: Research → Write → Review, each depending on the previous."""
        sm = TaskStateMachine(name="content-pipeline")
        research = sm.add_task(name="research")
        write = sm.add_task(name="write", parent_id=research)
        review = sm.add_task(name="review", parent_id=write)

        # Only research is ready initially
        assert sm.get_ready_tasks() == [research]

        # Complete research
        sm.transition(research, TaskState.RUNNING)
        sm.set_result(research, result={"findings": "data"})
        sm.transition(research, TaskState.COMPLETED)

        # Now write is ready
        assert sm.get_ready_tasks() == [write]

        # Complete write
        sm.transition(write, TaskState.RUNNING)
        sm.set_result(write, result={"draft": "content"})
        sm.transition(write, TaskState.COMPLETED)

        # Now review is ready
        assert sm.get_ready_tasks() == [review]

        # Complete review
        sm.transition(review, TaskState.RUNNING)
        sm.set_result(review, result={"approved": True})
        sm.transition(review, TaskState.COMPLETED)

        progress = sm.get_progress()
        assert progress["total"] == 3
        assert progress["completed"] == 3
        assert progress["progress_pct"] == 100.0

    def test_parallel_tasks_with_convergence(self):
        """Two independent tasks that both must complete before a final task."""
        sm = TaskStateMachine(name="parallel-merge")
        fetch_a = sm.add_task(name="fetch-a")
        fetch_b = sm.add_task(name="fetch-b")
        merge = sm.add_task(name="merge")
        # Manually set up merge to depend on both by making it a child of one
        # and adding the other as a "virtual" dependency via metadata.
        # For true multi-parent, we'd need DAG. Here we test parent-child only.

        # Both fetches are ready (no parents)
        ready = sm.get_ready_tasks()
        assert set(ready) == {fetch_a, fetch_b, merge}

        # Complete both fetches
        for tid in [fetch_a, fetch_b]:
            sm.transition(tid, TaskState.RUNNING)
            sm.transition(tid, TaskState.COMPLETED)

        progress = sm.get_progress()
        assert progress["by_state"]["completed"] == 2

    def test_retry_after_failure(self):
        sm = TaskStateMachine(name="retry-flow")
        tid = sm.add_task(name="api-call")

        # First attempt
        sm.transition(tid, TaskState.RUNNING)
        sm.set_error(tid, error="timeout")
        sm.transition(tid, TaskState.FAILED)

        # Retry
        sm.transition(tid, TaskState.PENDING, reason="retry attempt 2")
        sm.transition(tid, TaskState.RUNNING)
        sm.set_result(tid, result="success")
        sm.transition(tid, TaskState.COMPLETED)

        assert sm.get_progress()["completed"] == 1
        # PENDING→RUNNING, RUNNING→FAILED, FAILED→PENDING, PENDING→RUNNING, RUNNING→COMPLETED
        assert len(sm.tasks[tid].history) == 5

    def test_cancel_workflow(self):
        sm = TaskStateMachine(name="cancel-test")
        t1 = sm.add_task(name="a")
        t2 = sm.add_task(name="b")

        sm.transition(t1, TaskState.RUNNING)
        sm.transition(t1, TaskState.COMPLETED)

        sm.transition(t2, TaskState.RUNNING)
        sm.transition(t2, TaskState.CANCELLED)

        progress = sm.get_progress()
        assert progress["by_state"]["completed"] == 1
        assert progress["by_state"]["cancelled"] == 1

    def test_pause_and_resume(self):
        sm = TaskStateMachine(name="pause-test")
        tid = sm.add_task(name="long-task")

        sm.transition(tid, TaskState.RUNNING)
        sm.transition(tid, TaskState.PAUSED, reason="user paused")
        assert sm.tasks[tid].state == TaskState.PAUSED

        sm.transition(tid, TaskState.RUNNING, reason="user resumed")
        sm.transition(tid, TaskState.COMPLETED)
        assert sm.get_progress()["completed"] == 1

    def test_waiting_for_external_input(self):
        sm = TaskStateMachine(name="wait-test")
        tid = sm.add_task(name="approval-step")

        sm.transition(tid, TaskState.RUNNING)
        sm.transition(tid, TaskState.WAITING, reason="awaiting user approval")
        assert sm.tasks[tid].state == TaskState.WAITING

        # Simulate external input arriving
        sm.transition(tid, TaskState.RUNNING, reason="approval received")
        sm.transition(tid, TaskState.COMPLETED)
        assert sm.get_progress()["completed"] == 1

    def test_full_serialization_roundtrip(self):
        """Build a complex state and verify to_dict captures everything."""
        sm = TaskStateMachine(name="full-test")
        root1 = sm.add_task(name="root1", metadata={"team": "alpha"})
        root2 = sm.add_task(name="root2", metadata={"team": "beta"})
        child = sm.add_task(name="child", parent_id=root1)

        sm.transition(root1, TaskState.RUNNING)
        sm.transition(root1, TaskState.COMPLETED)
        sm.set_result(root1, result="r1-done")

        sm.transition(root2, TaskState.RUNNING)
        sm.set_error(root2, error="network error")
        sm.transition(root2, TaskState.FAILED)

        sm.transition(child, TaskState.RUNNING)

        d = sm.to_dict()
        assert d["name"] == "full-test"
        assert d["progress"]["total"] == 3
        assert d["progress"]["by_state"]["completed"] == 1
        assert d["progress"]["by_state"]["failed"] == 1
        assert d["progress"]["by_state"]["running"] == 1
        assert d["tasks"][root1]["result"] == "r1-done"
        assert d["tasks"][root2]["error"] == "network error"
        assert d["tasks"][root1]["metadata"] == {"team": "alpha"}
        assert d["tasks"][child]["parent_id"] == root1
        assert child in d["tasks"][root1]["children"]

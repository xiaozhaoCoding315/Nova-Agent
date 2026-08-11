"""Explicit state machine for multi-step task lifecycle management.

Provides a structured, visualization-friendly state machine that complements
the DAG workflow engine. While DAGWorkflow handles parallel execution of
independent nodes, TaskStateMachine adds:

- Explicit, validated state transitions (no illegal state changes)
- Full transition history / audit trail for each task
- Parent-child task hierarchies with dependency-aware scheduling
- Progress tracking and serialization for API/visualization
- Support for WAITING (external input) and PAUSED states

#
# Boundary: TaskStateMachine is the validated in-memory task lifecycle state
# machine (legal transitions + history). Durable persistence across restarts
# is TaskStateManager / TaskStore (Layer 4); per-run DAG node state is
# DAGNode.status.
"""
import time
import uuid
from enum import Enum
from typing import Optional, Any
from dataclasses import dataclass, field


class TaskState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING = "waiting"       # waiting for external input
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED = "paused"


# Valid state transitions
VALID_TRANSITIONS = {
    TaskState.PENDING: [TaskState.RUNNING, TaskState.CANCELLED],
    TaskState.RUNNING: [TaskState.COMPLETED, TaskState.FAILED, TaskState.PAUSED, TaskState.WAITING, TaskState.CANCELLED],
    TaskState.WAITING: [TaskState.RUNNING, TaskState.CANCELLED],
    TaskState.PAUSED: [TaskState.RUNNING, TaskState.CANCELLED],
    TaskState.FAILED: [TaskState.PENDING],  # retry
    TaskState.COMPLETED: [],
    TaskState.CANCELLED: [],
}


@dataclass
class StateTransition:
    from_state: TaskState
    to_state: TaskState
    timestamp: float
    reason: str = ""


@dataclass
class TaskNode:
    id: str
    name: str
    state: TaskState = TaskState.PENDING
    result: Any = None
    error: Optional[str] = None
    history: list = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    parent_id: Optional[str] = None
    children: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def transition(self, new_state: TaskState, reason: str = ""):
        if new_state not in VALID_TRANSITIONS.get(self.state, []):
            raise ValueError(f"Invalid transition: {self.state.value} -> {new_state.value}")
        old_state = self.state
        self.state = new_state
        self.updated_at = time.time()
        self.history.append(StateTransition(
            from_state=old_state,
            to_state=new_state,
            timestamp=self.updated_at,
            reason=reason,
        ))


class TaskStateMachine:
    """Manage multi-step task lifecycle with explicit state transitions.

    Unlike DAGWorkflow which focuses on parallel execution, this state machine
    emphasizes structured lifecycle management with validated transitions,
    audit trails, and visualization support.
    """

    def __init__(self, name: str):
        self.name = name
        self.id = str(uuid.uuid4())[:8]
        self.tasks: dict[str, TaskNode] = {}
        self.root_tasks: list[str] = []

    def add_task(self, name: str, parent_id: str = None, metadata: dict = None) -> str:
        tid = str(uuid.uuid4())[:8]
        task = TaskNode(id=tid, name=name, parent_id=parent_id, metadata=metadata or {})
        self.tasks[tid] = task
        if parent_id and parent_id in self.tasks:
            self.tasks[parent_id].children.append(tid)
        else:
            self.root_tasks.append(tid)
        return tid

    def transition(self, task_id: str, new_state: TaskState, reason: str = ""):
        if task_id not in self.tasks:
            raise KeyError(f"Task {task_id} not found")
        self.tasks[task_id].transition(new_state, reason)

    def set_result(self, task_id: str, result: Any):
        self.tasks[task_id].result = result
        self.tasks[task_id].updated_at = time.time()

    def set_error(self, task_id: str, error: str):
        self.tasks[task_id].error = error
        self.tasks[task_id].updated_at = time.time()

    def get_task(self, task_id: str) -> Optional[TaskNode]:
        return self.tasks.get(task_id)

    def get_ready_tasks(self) -> list[str]:
        """Get tasks that are PENDING and whose parents are COMPLETED."""
        ready = []
        for tid, task in self.tasks.items():
            if task.state != TaskState.PENDING:
                continue
            if task.parent_id:
                parent = self.tasks.get(task.parent_id)
                if parent and parent.state != TaskState.COMPLETED:
                    continue
            ready.append(tid)
        return ready

    def get_progress(self) -> dict:
        """Return progress summary."""
        states = {}
        for task in self.tasks.values():
            states[task.state.value] = states.get(task.state.value, 0) + 1
        total = len(self.tasks)
        completed = states.get(TaskState.COMPLETED.value, 0)
        return {
            "total": total,
            "completed": completed,
            "progress_pct": round(completed / total * 100, 1) if total else 0,
            "by_state": states,
        }

    def to_dict(self) -> dict:
        """Serialize for API response / visualization."""
        return {
            "id": self.id,
            "name": self.name,
            "progress": self.get_progress(),
            "tasks": {
                tid: {
                    "id": t.id,
                    "name": t.name,
                    "state": t.state.value,
                    "result": t.result,
                    "error": t.error,
                    "created_at": t.created_at,
                    "updated_at": t.updated_at,
                    "parent_id": t.parent_id,
                    "children": t.children,
                    "metadata": t.metadata,
                    "history": [
                        {
                            "from": h.from_state.value,
                            "to": h.to_state.value,
                            "timestamp": h.timestamp,
                            "reason": h.reason,
                        }
                        for h in t.history
                    ],
                }
                for tid, t in self.tasks.items()
            },
            "root_tasks": self.root_tasks,
        }

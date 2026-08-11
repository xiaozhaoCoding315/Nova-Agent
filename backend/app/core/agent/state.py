"""Task state management for DAG workflow execution.

Provides persistent state tracking for tasks, including:
- Task lifecycle (pending → running → completed/failed)
- State persistence (in-memory store, swappable for Redis/DB)
- Task history and audit trail
- Result caching

#
# Boundary: TaskStateManager is the durable task store facade (Layer 4). It
# snapshots task lifecycle to PostgreSQL via TaskStore. For validated state
# transitions use TaskStateMachine; DAGNode.status covers per-run node state.
"""
import time
import uuid
from enum import Enum
from typing import Any, Optional
from dataclasses import dataclass, field
from datetime import datetime


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


@dataclass
class TaskState:
    id: str
    name: str
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    error: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    elapsed_ms: Optional[float] = None
    retries: int = 0
    max_retries: int = 2
    parent_id: Optional[str] = None
    children_ids: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    history: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status.value,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "elapsed_ms": self.elapsed_ms,
            "retries": self.retries,
            "max_retries": self.max_retries,
            "parent_id": self.parent_id,
            "children_ids": self.children_ids,
            "metadata": self.metadata,
            "history": self.history,
        }


class TaskStateManager:
    """In-memory task state manager with lifecycle tracking.

    Can be extended to persist to Redis or database by overriding
    _persist() method.
    """

    def __init__(self):
        self._tasks: dict[str, TaskState] = {}
        self._results_cache: dict[str, Any] = {}

    def create_task(
        self,
        name: str,
        task_id: Optional[str] = None,
        parent_id: Optional[str] = None,
        max_retries: int = 2,
        metadata: Optional[dict] = None,
    ) -> TaskState:
        tid = task_id or str(uuid.uuid4())[:12]
        task = TaskState(
            id=tid,
            name=name,
            max_retries=max_retries,
            parent_id=parent_id,
            metadata=metadata or {},
        )
        self._tasks[tid] = task
        if parent_id and parent_id in self._tasks:
            parent = self._tasks[parent_id]
            if tid not in parent.children_ids:
                parent.children_ids.append(tid)
        self._add_history(task, "created", f"Task {name} created")
        return task

    def start_task(self, task_id: str) -> Optional[TaskState]:
        task = self._tasks.get(task_id)
        if task is None:
            return None
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now().isoformat()
        self._add_history(task, "started", f"Task {task.name} started")
        self._persist(task)
        return task

    def complete_task(self, task_id: str, result: Any = None) -> Optional[TaskState]:
        task = self._tasks.get(task_id)
        if task is None:
            return None
        task.status = TaskStatus.COMPLETED
        task.result = result
        task.completed_at = datetime.now().isoformat()
        if task.started_at:
            start = datetime.fromisoformat(task.started_at)
            end = datetime.fromisoformat(task.completed_at)
            task.elapsed_ms = (end - start).total_seconds() * 1000
        self._add_history(task, "completed", f"Task {task.name} completed")
        self._results_cache[task_id] = result
        self._persist(task)
        return task

    def fail_task(self, task_id: str, error: str) -> Optional[TaskState]:
        task = self._tasks.get(task_id)
        if task is None:
            return None
        if task.retries < task.max_retries:
            task.retries += 1
            task.status = TaskStatus.PENDING  # retryable
            self._add_history(task, "retry", f"Retry {task.retries}/{task.max_retries}: {error}")
        else:
            # Already at max retries — no more increments, just mark failed
            task.status = TaskStatus.FAILED
            task.error = error
            task.completed_at = datetime.now().isoformat()
            if task.started_at:
                start = datetime.fromisoformat(task.started_at)
                end = datetime.fromisoformat(task.completed_at)
                task.elapsed_ms = (end - start).total_seconds() * 1000
            self._add_history(task, "failed", f"Task {task.name} failed: {error}")
        self._persist(task)
        return task

    def cancel_task(self, task_id: str) -> Optional[TaskState]:
        task = self._tasks.get(task_id)
        if task is None:
            return None
        task.status = TaskStatus.CANCELLED
        task.completed_at = datetime.now().isoformat()
        self._add_history(task, "cancelled", f"Task {task.name} cancelled")
        self._persist(task)
        return task

    def skip_task(self, task_id: str, reason: str = "") -> Optional[TaskState]:
        task = self._tasks.get(task_id)
        if task is None:
            return None
        task.status = TaskStatus.SKIPPED
        task.error = reason
        task.completed_at = datetime.now().isoformat()
        self._add_history(task, "skipped", f"Task {task.name} skipped: {reason}")
        self._persist(task)
        return task

    def get_task(self, task_id: str) -> Optional[TaskState]:
        return self._tasks.get(task_id)

    def get_task_result(self, task_id: str) -> Any:
        task = self._tasks.get(task_id)
        if task and task.status == TaskStatus.COMPLETED:
            return task.result
        return self._results_cache.get(task_id)

    def get_children(self, task_id: str) -> list[TaskState]:
        task = self._tasks.get(task_id)
        if task is None:
            return []
        return [self._tasks[cid] for cid in task.children_ids if cid in self._tasks]

    def get_root_tasks(self) -> list[TaskState]:
        return [t for t in self._tasks.values() if t.parent_id is None]

    def get_all_tasks(self) -> list[TaskState]:
        return list(self._tasks.values())

    def get_summary(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for task in self._tasks.values():
            key = task.status.value
            counts[key] = counts.get(key, 0) + 1
        return {
            "total": len(self._tasks),
            "status_counts": counts,
            "tasks": {tid: t.to_dict() for tid, t in self._tasks.items()},
        }

    def clear(self) -> None:
        self._tasks.clear()
        self._results_cache.clear()

    def _add_history(self, task: TaskState, event: str, message: str) -> None:
        task.history.append({
            "event": event,
            "message": message,
            "timestamp": datetime.now().isoformat(),
        })

    def _persist(self, task: TaskState) -> None:
        """Hook for persistence. Override to save to Redis/DB."""
        pass

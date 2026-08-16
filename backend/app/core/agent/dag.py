"""DAG-based dynamic workflow engine for complex task execution.

Supports:
- Dependency-aware node scheduling (topological sort)
- Parallel execution of independent nodes
- Retry with configurable max_retries
- Dependency failure propagation (child nodes marked SKIPPED)
"""
import asyncio
import time
import uuid
from enum import Enum
from typing import Callable, Any, Optional
from dataclasses import dataclass, field


class NodeStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class DAGNode:
    """A node in a DAG workflow execution.

    Its `status` tracks the node lifecycle within a single in-memory DAG run;
    it is ephemeral (dies with the run). For durable, validated task lifecycle
    tracking use TaskStateMachine (in-memory, validated) and TaskStateManager
    (durable store, Layer 4).
    """
    id: str
    name: str
    func: Callable  # async callable
    args: tuple = ()
    kwargs: dict = field(default_factory=dict)
    dependencies: list = field(default_factory=list)  # list of node IDs
    status: NodeStatus = NodeStatus.PENDING
    result: Any = None
    error: Optional[str] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    retries: int = 0
    max_retries: int = 2

    @property
    def elapsed_ms(self) -> Optional[float]:
        if self.start_time is None:
            return None
        end = self.end_time if self.end_time is not None else time.time()
        return (end - self.start_time) * 1000


class DAGWorkflow:
    """Directed Acyclic Graph workflow executor with parallel node execution."""

    def __init__(self, name: str = "workflow"):
        self.id = str(uuid.uuid4())[:8]
        self.name = name
        self.nodes: dict[str, DAGNode] = {}

    def add_node(self, node: DAGNode) -> "DAGWorkflow":
        if node.id in self.nodes:
            raise ValueError(f"Duplicate node id: {node.id}")
        self.nodes[node.id] = node
        return self

    def _validate(self) -> None:
        """Check all dependencies exist and there are no cycles (topo sort)."""
        for nid, node in self.nodes.items():
            for dep in node.dependencies:
                if dep not in self.nodes:
                    raise ValueError(
                        f"Node {nid} depends on unknown node {dep}"
                    )
        # cycle check via topological sort (Kahn's algorithm)
        self._topological_sort()

    def _topological_sort(self) -> list[str]:
        """Return node IDs in topological order using Kahn's algorithm."""
        in_degree = {nid: len(self.nodes[nid].dependencies) for nid in self.nodes}

        # Build adjacency: dep -> list of dependents
        dependents: dict[str, list[str]] = {nid: [] for nid in self.nodes}
        for nid, node in self.nodes.items():
            for dep in node.dependencies:
                dependents[dep].append(nid)

        queue = [nid for nid, deg in in_degree.items() if deg == 0]
        order: list[str] = []
        while queue:
            nid = queue.pop(0)
            order.append(nid)
            for dependent in dependents[nid]:
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)

        if len(order) != len(self.nodes):
            raise ValueError("Cycle detected in DAG")
        return order

    def _node_ready(self, node: DAGNode) -> bool:
        """Node is runnable if all dependencies are COMPLETED."""
        if node.status != NodeStatus.PENDING:
            return False
        for dep_id in node.dependencies:
            dep_node = self.nodes[dep_id]
            if dep_node.status == NodeStatus.FAILED:
                # propagate failure: skip this node
                node.status = NodeStatus.SKIPPED
                node.error = f"Dependency {dep_id} failed"
                return False
            if dep_node.status != NodeStatus.COMPLETED:
                return False
        return True

    def _resolve_args(self, node: DAGNode) -> tuple:
        """Resolve node args.

        If a node has dependencies and no explicit args, dependency results
        are passed as positional args. Otherwise the node's own args are used.
        """
        if node.dependencies and not node.args:
            return tuple(self.nodes[dep_id].result for dep_id in node.dependencies)
        return node.args

    async def _run_node(self, node: DAGNode) -> None:
        """Execute a single node with retry logic."""
        node.status = NodeStatus.RUNNING
        node.start_time = time.time()
        while node.retries <= node.max_retries:
            try:
                args = self._resolve_args(node)
                raw = node.func(*args, **node.kwargs)
                # Support both sync callables and async coroutines
                if asyncio.iscoroutine(raw):
                    result = await raw
                else:
                    result = raw
                node.result = result
                node.status = NodeStatus.COMPLETED
                node.end_time = time.time()
                return
            except Exception as e:
                node.retries += 1
                node.error = str(e)
                if node.retries > node.max_retries:
                    node.status = NodeStatus.FAILED
                    node.end_time = time.time()
                    return
        # Should not reach here but safety fallback
        node.status = NodeStatus.FAILED
        node.end_time = time.time()

    async def execute(self, context: Optional[dict] = None) -> dict[str, DAGNode]:
        """Execute the DAG, running ready nodes in parallel batches."""
        self._validate()
        # Inject context into each node's kwargs if provided and func accepts it
        pending_count = len(self.nodes)
        completed_count = 0

        while completed_count < pending_count:
            # Find all ready nodes
            ready: list[DAGNode] = []
            for node in self.nodes.values():
                if self._node_ready(node):
                    ready.append(node)

            if not ready:
                # No ready nodes but we haven't completed all — deadlock check
                remaining = [
                    n for n in self.nodes.values()
                    if n.status == NodeStatus.PENDING
                ]
                if remaining:
                    # This shouldn't happen after topological validation
                    for n in remaining:
                        n.status = NodeStatus.FAILED
                        n.error = "Deadlock: dependencies never satisfied"
                        n.end_time = time.time()
                        completed_count += 1
                    break
                break

            # Execute all ready nodes in parallel
            tasks = [asyncio.create_task(self._run_node(node)) for node in ready]
            await asyncio.gather(*tasks, return_exceptions=True)

            # Count terminal states
            completed_count = sum(
                1 for n in self.nodes.values()
                if n.status in (NodeStatus.COMPLETED, NodeStatus.FAILED, NodeStatus.SKIPPED)
            )

        return self.nodes

    async def execute_streaming(self):
        """Execute DAG with streaming events for frontend visualization."""
        executed = set()
        in_progress = set()

        while len(executed) < len(self.nodes):
            # Find nodes whose deps are all executed
            batch = []
            for nid, node in self.nodes.items():
                if nid in executed or nid in in_progress:
                    continue
                if all(dep in executed for dep in node.dependencies):
                    batch.append(nid)

            if not batch:
                break

            # Mark as in_progress and yield started events
            for nid in batch:
                in_progress.add(nid)
                yield {
                    "type": "node_started",
                    "node_id": nid,
                    "node_name": self.nodes[nid].name,
                }

            # Execute batch in parallel
            tasks = []
            for nid in batch:
                node = self.nodes[nid]
                tasks.append(self._execute_node(node))

            results = await asyncio.gather(*tasks, return_exceptions=True)

            for nid, result in zip(batch, results):
                executed.add(nid)
                in_progress.discard(nid)

                if isinstance(result, Exception):
                    yield {"type": "node_failed", "node_id": nid, "error": str(result)}
                else:
                    yield {
                        "type": "node_completed",
                        "node_id": nid,
                        "result": result,
                    }

        yield {"type": "dag_completed", "total_nodes": len(self.nodes)}

    async def _execute_node(self, node):
        """Execute a single node's function."""
        func = node.func
        args = node.args
        kwargs = node.kwargs
        if func:
            result = func(*args, **kwargs)
            if asyncio.iscoroutine(result):
                result = await result
            return result
        return {"status": "no_op"}

    async def execute_race_streaming(self, race_enabled: bool = True):
        """Execute the DAG, streaming node events; sibling nodes run in parallel.

        NOTE: the historical "race" semantics — where ready sibling nodes raced
        and the first to finish cancelled the rest — were a bug and are removed.
        Every ready node now runs to completion independently and failures
        propagate to dependents (children of a failed node are SKIPPED).
        True provider-level racing (multiple LLMs for one request, take the
        fastest) lives in app.core.agent.race.RaceStrategy.

        The `race_enabled` parameter is retained for API compatibility only;
        sibling nodes always run in parallel.
        """
        self._validate()  # raises ValueError on missing deps or cycles
        executed: set[str] = set()
        failed: set[str] = set()
        in_progress: set[str] = set()

        while len(executed) < len(self.nodes):
            batch: list[str] = []
            for nid, node in self.nodes.items():
                if nid in executed or nid in in_progress:
                    continue
                if any(dep in failed for dep in node.dependencies):
                    # Dependency failed: skip this node
                    node.status = NodeStatus.SKIPPED
                    node.error = f"Dependency {next(dep for dep in node.dependencies if dep in failed)} failed"
                    executed.add(nid)
                    failed.add(nid)
                    yield {"type": "node_failed", "node_id": nid, "error": node.error}
                    continue
                if all(dep in executed for dep in node.dependencies):
                    batch.append(nid)
            if not batch:
                break

            for nid in batch:
                in_progress.add(nid)
                yield {"type": "node_started", "node_id": nid, "node_name": self.nodes[nid].name}

            results = await asyncio.gather(
                *[self._safe_execute(self.nodes[nid]) for nid in batch],
                return_exceptions=True,
            )

            for nid, result in zip(batch, results):
                node = self.nodes[nid]
                executed.add(nid)
                in_progress.discard(nid)
                if isinstance(result, BaseException):
                    node.status = NodeStatus.FAILED
                    node.error = str(result)
                    failed.add(nid)
                    yield {"type": "node_failed", "node_id": nid, "error": str(result)}
                else:
                    node.status = NodeStatus.COMPLETED
                    node.result = result
                    yield {"type": "node_completed", "node_id": nid, "result": result}

        yield {"type": "dag_completed", "total_nodes": len(self.nodes)}

    async def _safe_execute(self, node):
        """Execute a node's function, supporting both sync and async callables."""
        func = node.func
        args = node.args or ()
        kwargs = node.kwargs or {}
        if func:
            result = func(*args, **kwargs)
            if asyncio.iscoroutine(result):
                result = await result
            return result
        return {"status": "no_op"}

    def get_ready_completed_nodes(self):
        """Return node IDs that have no dependencies (ready to run immediately)."""
        return [nid for nid, n in self.nodes.items() if not n.dependencies]

    def get_results(self) -> dict[str, Any]:
        """Return final results keyed by node id."""
        return {
            nid: node.result
            for nid, node in self.nodes.items()
            if node.status == NodeStatus.COMPLETED
        }

    def get_status(self) -> dict[str, Any]:
        """Return a summary of the workflow status."""
        statuses: dict[str, int] = {}
        for node in self.nodes.values():
            key = node.status.value
            statuses[key] = statuses.get(key, 0) + 1
        return {
            "workflow_id": self.id,
            "workflow_name": self.name,
            "total_nodes": len(self.nodes),
            "status_counts": statuses,
            "nodes": {
                nid: {
                    "status": n.status.value,
                    "elapsed_ms": round(n.elapsed_ms, 1) if n.elapsed_ms else None,
                    "error": n.error,
                    "retries": n.retries,
                }
                for nid, n in self.nodes.items()
            },
        }

"""Durable task state storage — Layer 4: DAG runtime breakpoint memory."""
from typing import Any, Optional
import psycopg
from app.db import query, execute


class TaskStore:
    """Persist task lifecycle snapshots to PostgreSQL.

    Layer 4 of the memory architecture: DAG/task runtime state survives
    restarts, enabling resumption and post-mortem review.
    """

    @staticmethod
    async def save(task: Any) -> None:
        """Upsert a TaskState snapshot (accepts TaskState or dict)."""
        data = task.to_dict() if hasattr(task, "to_dict") else task
        await execute(
            """
            INSERT INTO task_states (
                id, name, status, result, error, created_at, started_at,
                completed_at, retries, max_retries, parent_id, children_ids,
                metadata, history
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                status = EXCLUDED.status,
                result = EXCLUDED.result,
                error = EXCLUDED.error,
                completed_at = EXCLUDED.completed_at,
                retries = EXCLUDED.retries,
                children_ids = EXCLUDED.children_ids,
                metadata = EXCLUDED.metadata,
                history = EXCLUDED.history
            """,
            (
                data["id"], data["name"], data["status"],
                psycopg.types.json.Json(data.get("result")), data.get("error"),
                data.get("created_at"), data.get("started_at"), data.get("completed_at"),
                data.get("retries", 0), data.get("max_retries", 2), data.get("parent_id"),
                psycopg.types.json.Json(data.get("children_ids", [])),
                psycopg.types.json.Json(data.get("metadata", {})),
                psycopg.types.json.Json(data.get("history", [])),
            ),
        )

    @staticmethod
    async def get(task_id: str) -> Optional[dict]:
        rows = await query(
            "SELECT id, name, status, result, error, created_at, started_at, "
            "completed_at, retries, max_retries, parent_id, children_ids, "
            "metadata, history FROM task_states WHERE id = %s",
            (task_id,),
        )
        if not rows:
            return None
        r = rows[0]
        return {
            "id": r[0], "name": r[1], "status": r[2],
            "result": r[3] if r[3] is not None else None, "error": r[4],
            "created_at": str(r[5]) if r[5] else None,
            "started_at": str(r[6]) if r[6] else None,
            "completed_at": str(r[7]) if r[7] else None,
            "retries": r[8] or 0, "max_retries": r[9] or 2, "parent_id": r[10],
            "children_ids": r[11] or [], "metadata": r[12] or {},
            "history": r[13] or [],
        }

    @staticmethod
    async def list(limit: int = 50, status: Optional[str] = None) -> list[dict]:
        if status:
            rows = await query(
                "SELECT id, name, status, created_at FROM task_states "
                "WHERE status = %s ORDER BY created_at DESC LIMIT %s",
                (status, limit),
            )
        else:
            rows = await query(
                "SELECT id, name, status, created_at FROM task_states "
                "ORDER BY created_at DESC LIMIT %s",
                (limit,),
            )
        return [
            {"id": r[0], "name": r[1], "status": r[2], "created_at": str(r[3]) if r[3] else None}
            for r in rows
        ]

    @staticmethod
    async def clear() -> int:
        rows = await query("SELECT COUNT(*) FROM task_states")
        n = rows[0][0] if rows else 0
        await execute("DELETE FROM task_states")
        return n

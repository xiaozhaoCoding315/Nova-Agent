"""Durable chat-turn state: one active turn per session, replayable events."""
import psycopg

from app.db import execute, query

ACTIVE_STATUSES = ("queued", "running")
TERMINAL_STATUSES = ("succeeded", "failed", "canceled", "interrupted")

_COLUMNS = (
    "id, session_id, user_id, status, cancel_requested, error, "
    "user_message_id, assistant_message_id, job_id, "
    "created_at, updated_at, finished_at"
)


def _turn(row) -> dict:
    return {
        "id": str(row[0]),
        "session_id": str(row[1]),
        "user_id": int(row[2]),
        "status": row[3],
        "cancel_requested": bool(row[4]),
        "error": row[5],
        "user_message_id": int(row[6]) if row[6] is not None else None,
        "assistant_message_id": int(row[7]) if row[7] is not None else None,
        "job_id": str(row[8]) if row[8] else None,
        "created_at": row[9],
        "updated_at": row[10],
        "finished_at": row[11],
    }


async def create_turn(
    turn_id: str, session_id: str, user_id: int, user_message_id: int,
) -> dict | None:
    try:
        rows = await execute(
            f"""
            INSERT INTO turns (id, session_id, user_id, user_message_id)
            SELECT %s, %s, %s, %s
            WHERE NOT EXISTS (
                SELECT 1 FROM turns
                WHERE session_id = %s AND status IN ('queued', 'running')
            )
            RETURNING {_COLUMNS}
            """,
            (turn_id, session_id, user_id, user_message_id, session_id),
        )
    except psycopg.errors.UniqueViolation:
        return None
    return _turn(rows[0]) if rows else None


async def get_turn(turn_id: str, user_id: int | None = None) -> dict | None:
    sql = f"SELECT {_COLUMNS} FROM turns WHERE id = %s"
    params: tuple = (turn_id,)
    if user_id is not None:
        sql += " AND user_id = %s"
        params = (turn_id, user_id)
    rows = await query(sql, params)
    return _turn(rows[0]) if rows else None


async def _one_for_session(
    session_id: str, user_id: int | None, *, active_only: bool,
) -> dict | None:
    sql = f"SELECT {_COLUMNS} FROM turns WHERE session_id = %s"
    params: list = [session_id]
    if user_id is not None:
        sql += " AND user_id = %s"
        params.append(user_id)
    if active_only:
        sql += " AND status IN ('queued', 'running')"
    sql += " ORDER BY created_at DESC LIMIT 1"
    rows = await query(sql, tuple(params))
    return _turn(rows[0]) if rows else None


async def get_active_turn(session_id: str, user_id: int | None = None) -> dict | None:
    return await _one_for_session(session_id, user_id, active_only=True)


async def get_latest_turn(session_id: str, user_id: int | None = None) -> dict | None:
    return await _one_for_session(session_id, user_id, active_only=False)


async def set_job_id(turn_id: str, job_id: str) -> None:
    await execute(
        "UPDATE turns SET job_id = %s, updated_at = now() WHERE id = %s",
        (job_id, turn_id),
    )


async def start_turn(turn_id: str) -> bool:
    rows = await execute(
        "UPDATE turns SET status = 'running', updated_at = now() "
        "WHERE id = %s AND status = 'queued' RETURNING id",
        (turn_id,),
    )
    return bool(rows)


async def request_cancel(turn_id: str) -> str | None:
    rows = await execute(
        "UPDATE turns SET cancel_requested = TRUE, "
        "status = CASE WHEN status = 'queued' THEN 'canceled' ELSE status END, "
        "finished_at = CASE WHEN status = 'queued' THEN now() ELSE finished_at END, "
        "updated_at = now() "
        "WHERE id = %s AND status IN ('queued', 'running') RETURNING status",
        (turn_id,),
    )
    return rows[0][0] if rows else None


async def is_cancel_requested(turn_id: str) -> bool:
    rows = await query(
        "SELECT cancel_requested, status FROM turns WHERE id = %s", (turn_id,)
    )
    if not rows:
        return True
    return bool(rows[0][0]) or rows[0][1] == "canceled"


async def finish_turn(
    turn_id: str,
    status: str,
    *,
    error: str | None = None,
    assistant_message_id: int | None = None,
) -> None:
    await execute(
        "UPDATE turns SET status = %s, error = %s, "
        "assistant_message_id = COALESCE(%s, assistant_message_id), "
        "updated_at = now(), finished_at = now() "
        "WHERE id = %s AND status IN ('queued', 'running')",
        (status, error, assistant_message_id, turn_id),
    )


async def recover_interrupted_turns() -> int:
    rows = await execute(
        "UPDATE turns SET status = 'interrupted', "
        "error = 'server restarted before the turn finished', "
        "updated_at = now(), finished_at = now() "
        "WHERE status IN ('queued', 'running') RETURNING id",
        None,
    )
    return len(rows)


async def cleanup_old_turns(days: int = 30) -> int:
    rows = await execute(
        "DELETE FROM turns WHERE status NOT IN ('queued', 'running') "
        "AND created_at < now() - make_interval(days => %s) RETURNING id",
        (days,),
    )
    return len(rows)

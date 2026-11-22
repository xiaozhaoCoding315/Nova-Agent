"""Small typed helpers around the global job runner."""
from app.core.jobs.runner import runner
from app.db import query


def is_running() -> bool:
    return runner.running


async def enqueue_index(
    repo_id: str,
    *,
    reindex: bool = False,
    force: bool = False,
    user_id: int | None = None,
    idempotency_key: str | None = None,
) -> str:
    return await runner.enqueue(
        "index",
        {"repo_id": repo_id, "reindex": reindex, "force": force},
        user_id=user_id,
        idempotency_key=idempotency_key,
    )


async def enqueue_task(
    task_id: str,
    *,
    user_id: int | None = None,
    idempotency_key: str | None = None,
) -> str:
    return await runner.enqueue(
        "task",
        {"task_id": task_id},
        user_id=user_id,
        idempotency_key=idempotency_key,
    )


async def enqueue_verify(
    repo_id: str,
    user_id: int,
    *,
    permission_mode: str | None = None,
    approval_granted: bool = False,
) -> str:
    return await runner.enqueue(
        "verify",
        {
            "repo_id": repo_id,
            "permission_mode": permission_mode,
            "approval_granted": approval_granted,
        },
        user_id=user_id,
    )


async def enqueue_builder_plan(
    repo_id: str,
    *,
    user_id: int | None = None,
) -> str:
    return await runner.enqueue(
        "builder_plan", {"repo_id": repo_id}, user_id=user_id
    )


async def enqueue_builder_files(
    repo_id: str,
    feedback: str = "",
    *,
    user_id: int | None = None,
) -> str:
    return await runner.enqueue(
        "builder_files",
        {"repo_id": repo_id, "feedback": feedback},
        user_id=user_id,
    )


async def enqueue_session_summary(session_id: str, user_id: int) -> str | None:
    """Queue a summary if the runner is live; otherwise skip silently.

    Tests and one-off scripts often run without the FastAPI lifespan.  Memory
    compression is best-effort and must never break a chat turn.  The
    idempotency key is tied to the newest message so repeated enqueues for the
    same batch collapse into one durable job.
    """
    if not runner.running:
        return None
    rows = await query(
        "SELECT COALESCE(MAX(id), 0) FROM messages WHERE session_id = %s",
        (session_id,),
    )
    last_id = int(rows[0][0] or 0) if rows else 0
    key = f"session_summary:{session_id}:{last_id}" if last_id else None
    return await runner.enqueue(
        "session_summary",
        {"session_id": session_id, "user_id": user_id},
        user_id=user_id,
        idempotency_key=key,
        max_attempts=3,
    )


async def enqueue_facts_extract(
    session_id: str,
    user_id: int,
    user_message_id: int,
    assistant_message_id: int,
    scope_type: str,
    scope_id: str = "",
) -> str | None:
    """Queue fact extraction for one completed turn (durable, retryable)."""
    if not runner.running:
        return None
    return await runner.enqueue(
        "facts_extract",
        {
            "session_id": session_id,
            "user_id": user_id,
            "user_message_id": int(user_message_id),
            "assistant_message_id": int(assistant_message_id),
            "scope_type": scope_type,
            "scope_id": scope_id,
        },
        user_id=user_id,
        idempotency_key=f"facts_extract:{assistant_message_id}",
        max_attempts=3,
    )


async def enqueue_chat_turn(
    turn_id: str, session_id: str, user_id: int,
) -> str | None:
    """Queue a chat turn; ``None`` means the runner is disabled (inline mode)."""
    if not runner.running:
        return None
    return await runner.enqueue(
        "chat_turn",
        {"turn_id": turn_id, "session_id": session_id},
        user_id=user_id,
    )

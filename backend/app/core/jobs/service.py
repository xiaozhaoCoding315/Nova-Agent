"""Small typed helpers around the global job runner."""
from app.core.jobs.runner import runner


def is_running() -> bool:
    return runner.running


async def enqueue_index(
    repo_id: str,
    *,
    reindex: bool = False,
    user_id: int | None = None,
    idempotency_key: str | None = None,
) -> str:
    return await runner.enqueue(
        "index",
        {"repo_id": repo_id, "reindex": reindex},
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


async def enqueue_verify(repo_id: str, user_id: int) -> str:
    return await runner.enqueue("verify", {"repo_id": repo_id}, user_id=user_id)


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
    compression is best-effort and must never break a chat turn.
    """
    if not runner.running:
        return None
    return await runner.enqueue(
        "session_summary",
        {"session_id": session_id, "user_id": user_id},
        user_id=user_id,
    )


async def enqueue_change_spec(change_id: str, user_id: int, idempotency_key: str | None = None) -> str:
    return await runner.enqueue(
        "change_spec", {"change_id": change_id}, user_id=user_id,
        idempotency_key=idempotency_key,
    )


async def enqueue_change_plan(change_id: str, user_id: int) -> str:
    return await runner.enqueue(
        "change_plan", {"change_id": change_id}, user_id=user_id
    )


async def enqueue_change_execute(change_id: str, user_id: int) -> str:
    return await runner.enqueue(
        "change_execute", {"change_id": change_id, "user_id": user_id},
        user_id=user_id,
    )

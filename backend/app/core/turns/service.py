"""Background execution of one chat turn, decoupled from the HTTP request."""
import asyncio
import contextlib
import time

import structlog

from app.core.agent.loop import run_chat
from app.core.memory import session as session_mod
from app.core.security.accounts import get_user_by_id
from app.core.security.redaction import redact_text
from app.core.turns import events, store

logger = structlog.get_logger()

_TICK_SECONDS = 0.4
_CANCEL_POLL_SECONDS = 1.0
_background_tasks: set[asyncio.Task] = set()


def start_turn_task(turn_id: str) -> None:
    """Inline fallback used when the JobRunner is disabled (tests, local edge)."""
    task = asyncio.create_task(execute_turn(turn_id), name=f"nova-turn-{turn_id}")
    _background_tasks.add(task)

    def _done(finished: asyncio.Task) -> None:
        _background_tasks.discard(finished)
        if finished.cancelled():
            return
        error = finished.exception()
        if error:
            logger.warning("turn_task_failed", turn_id=turn_id, error=str(error))

    task.add_done_callback(_done)


async def _stop_generator(
    pending: asyncio.Task | None, generator,
) -> None:
    if pending is not None and not pending.done():
        pending.cancel()
    if pending is not None:
        with contextlib.suppress(BaseException):
            await pending
    with contextlib.suppress(BaseException):
        await generator.aclose()


async def execute_turn(turn_id: str) -> str:
    turn = await store.get_turn(turn_id)
    if not turn:
        return "missing"
    if turn["status"] not in store.ACTIVE_STATUSES:
        return turn["status"]
    if not await store.start_turn(turn_id):
        fresh = await store.get_turn(turn_id)
        return fresh["status"] if fresh else "missing"

    session = await session_mod.get_session(turn["session_id"], turn["user_id"])
    message = (
        await session_mod.get_message(turn["user_message_id"], turn["session_id"])
        if turn.get("user_message_id")
        else None
    )
    user = await get_user_by_id(turn["user_id"])
    if not session or not message or not user:
        await store.finish_turn(turn_id, "failed", error="任务上下文已丢失，无法继续")
        return "failed"

    seq = await events.max_seq(turn_id)
    coalescer = events.EventCoalescer()
    assistant_message_id: int | None = None

    async def _append(kind: str, payload: dict) -> None:
        nonlocal seq
        seq += 1
        await events.append_event(turn_id, seq, kind, payload)

    async def _flush(items: list[tuple[str, dict]]) -> None:
        for kind, payload in items:
            await _append(kind, payload)

    generator = run_chat(
        user,
        session,
        message["content"],
        session.get("repo_ids") or [],
        turn_id=turn_id,
        attachments=message.get("attachments") or [],
        persist_on_cancel=True,
    )
    pending: asyncio.Task | None = None
    last_cancel_check = 0.0
    try:
        while True:
            if pending is None:
                pending = asyncio.create_task(generator.__anext__())
            try:
                event = await asyncio.wait_for(
                    asyncio.shield(pending), timeout=_TICK_SECONDS,
                )
                pending = None
            except asyncio.TimeoutError:
                now = time.monotonic()
                await _flush(coalescer.flush_if_due(now))
                if now - last_cancel_check >= _CANCEL_POLL_SECONDS:
                    last_cancel_check = now
                    if await store.is_cancel_requested(turn_id):
                        await _stop_generator(pending, generator)
                        pending = None
                        await _flush(coalescer.flush())
                        await store.finish_turn(turn_id, "canceled")
                        return "canceled"
                continue
            except StopAsyncIteration:
                pending = None
                break

            await _flush(coalescer.feed(event))
            if event.get("event") == "done":
                message_id = (event.get("data") or {}).get("message_id")
                if isinstance(message_id, int) and message_id > 0:
                    assistant_message_id = message_id

        await _flush(coalescer.flush())
        await store.finish_turn(
            turn_id, "succeeded", assistant_message_id=assistant_message_id,
        )
        return "succeeded"
    except asyncio.CancelledError:
        await _stop_generator(pending, generator)
        pending = None
        with contextlib.suppress(Exception):
            await _flush(coalescer.flush())
        canceled = True
        with contextlib.suppress(Exception):
            canceled = await store.is_cancel_requested(turn_id)
        await store.finish_turn(
            turn_id,
            "canceled" if canceled else "interrupted",
            error=None if canceled else "服务重启或关闭，任务已中断",
        )
        raise
    except Exception as exc:  # noqa: BLE001
        detail = redact_text(f"{type(exc).__name__}: {exc}")[:2000]
        logger.exception("turn_execution_failed", turn_id=turn_id)
        # The stream may still be live when the failure came from event
        # persistence: stop it so it cannot keep generating unrecorded output.
        await _stop_generator(pending, generator)
        pending = None
        with contextlib.suppress(Exception):
            await _flush(coalescer.flush())
        with contextlib.suppress(Exception):
            await _append("error", {"code": "turn_failed", "message": "任务执行失败"})
        with contextlib.suppress(Exception):
            await store.finish_turn(turn_id, "failed", error=detail)
        return "failed"
    finally:
        with contextlib.suppress(BaseException):
            await generator.aclose()

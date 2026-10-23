"""Single place that writes LLM usage, regardless of entrypoint.

Every chat turn, background task, builder call and memory extraction records
here so daily token budgets cannot be bypassed by using a non-chat feature.
"""
import structlog

from app.db import execute

logger = structlog.get_logger()


async def record_usage(
    user_id: int | None,
    session_id: str | None,
    usage: dict | None,
    *,
    tool_calls: int = 0,
    source: str = "chat",
) -> None:
    if not user_id or not usage:
        return
    try:
        await execute(
            "INSERT INTO usage_log "
            "(user_id, session_id, model, prompt_tokens, completion_tokens, tool_calls, source) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (
                user_id,
                session_id or None,
                str(usage.get("model") or "unknown")[:64],
                int(usage.get("prompt_tokens") or 0),
                int(usage.get("completion_tokens") or 0),
                int(tool_calls or 0),
                source[:20],
            ),
        )
    except Exception as exc:  # noqa: BLE001 — accounting must never break a turn
        logger.warning("usage_record_failed", source=source, error=str(exc))

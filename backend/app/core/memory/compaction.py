"""Recoverable in-turn compaction.

The context governor shrinks old tool results in place, but truncation alone
loses decisions and unfinished work.  Before the first compaction of a turn we
ask the utility model for a structured summary, persist it, and keep it in the
system prompt for the rest of the turn.  A later turn can re-inject the latest
record when the rolling session summary has not caught up yet.
"""
import json

import structlog

from app.config import settings
from app.core.llm.json_call import llm_json
from app.core.security.limits import ensure_token_budget
from app.core.security.redaction import redact_text
from app.db import execute, query

logger = structlog.get_logger()

MAX_COMPACTION_CHARS = 4000
MAX_MESSAGE_CHARS = 1500
MAX_MESSAGES = 40

_PROMPT = """把下面较早的一段任务对话压缩成供同一任务继续使用的结构化中文摘要。
保留：用户目标、已确认的决策、技术约束、未完成事项、关键文件/命令/错误结论、用户偏好。
不要保留：寒暄、重复内容、完整代码、工具原始输出。
最多 40 行，直接输出 JSON：{{"summary": "..."}}

对话：
{conversation}"""


def _format_messages(messages: list[dict]) -> str:
    parts: list[str] = []
    for message in messages[-MAX_MESSAGES:]:
        role = message.get("role")
        if role == "system":
            continue
        label = "用户" if role == "user" else "工具" if role == "tool" else "助手"
        content = message.get("content")
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False, default=str)
        text = redact_text(content.strip())[:MAX_MESSAGE_CHARS]
        if text:
            parts.append(f"{label}: {text}")
    return "\n\n".join(parts)


def _truncate(text: str) -> str:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    return "\n".join(lines[:40])[:MAX_COMPACTION_CHARS]


async def summarize_for_compaction(
    user_id: int, session_id: str, messages: list[dict], turn_id: str | None = None,
) -> str:
    """Return a structured summary of the messages about to be compacted."""
    conversation = _format_messages(messages)
    if not conversation:
        return ""
    await ensure_token_budget(user_id=user_id)
    try:
        data = await llm_json(
            _PROMPT.format(conversation=conversation[:30000]),
            timeout=settings.llm_timeout,
            user_id=user_id,
            session_id=session_id,
            source="memory", purpose="utility",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "compaction_summary_failed", session=session_id, error=str(exc)
        )
        return ""
    return _truncate(str(data.get("summary") or data.get("text") or ""))


async def record_compaction(
    session_id: str,
    summary: str,
    *,
    turn_id: str | None = None,
    message_count: int = 0,
    tokens_before: int = 0,
    tokens_after: int = 0,
) -> int | None:
    """Persist a compaction record; never let memory bookkeeping break a turn."""
    if not summary.strip():
        return None
    try:
        rows = await execute(
            "INSERT INTO compaction_records "
            "(session_id, turn_id, summary, message_count, tokens_before, tokens_after) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (
                session_id, turn_id, summary, message_count,
                tokens_before, tokens_after,
            ),
        )
        return int(rows[0][0]) if rows else None
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "compaction_record_failed", session=session_id, error=str(exc)
        )
        return None


async def latest_compaction(session_id: str, user_id: int) -> str:
    """Latest persisted compaction summary owned by ``user_id``."""
    try:
        rows = await query(
            "SELECT c.summary FROM compaction_records c "
            "JOIN sessions s ON s.id = c.session_id "
            "WHERE c.session_id = %s AND s.user_id = %s "
            "ORDER BY c.id DESC LIMIT 1",
            (session_id, user_id),
        )
        return str(rows[0][0] or "") if rows else ""
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "compaction_load_failed", session=session_id, error=str(exc)
        )
        return ""

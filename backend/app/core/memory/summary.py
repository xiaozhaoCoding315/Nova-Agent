"""Rolling session summaries (short-term memory compression).

Messages are summarized in batches once a session grows past the threshold.
``summary_upto_id`` records the last message folded into the summary so the
next pass only processes new turns and recent messages stay verbatim.
"""
import structlog

from app.config import settings
from app.core.llm.json_call import llm_json
from app.core.memory import session as session_mod
from app.core.security.limits import ensure_token_budget
from app.core.security.redaction import redact_text

logger = structlog.get_logger()

KEEP_RECENT = 8            # recent messages stay verbatim in the prompt
SUMMARY_BATCH = 20         # new user/assistant messages before compressing
MAX_SUMMARY_LINES = 40
MAX_SUMMARY_CHARS = 2000

_PROMPT = """请压缩下面这段较早的对话，生成一份供后续对话使用的中文摘要。
保留：用户目标、已确认的决策、技术约束、未完成事项、重要偏好与结论。
不要保留：寒暄、重复内容、大段代码、工具原始输出。
最多 40 行，直接输出 JSON：{{"summary": "..."}}

已有摘要（可能为空）：
{previous}

需要合并的新对话：
{conversation}"""


def _truncate(text: str) -> str:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    return "\n".join(lines[:MAX_SUMMARY_LINES])[:MAX_SUMMARY_CHARS]


def _format_messages(rows: list[tuple]) -> str:
    parts = []
    for role, content in rows:
        label = "用户" if role == "user" else "助手"
        parts.append(f"{label}: {redact_text((content or '').strip())[:800]}")
    return "\n\n".join(parts)


async def maybe_summarize(
    session_id: str, user_id: int, ctx=None
) -> int:
    """Compress new messages when the batch is large enough.

    Returns the number of messages folded into the summary (0 when skipped).
    """
    rows = await session_mod.summary_state(session_id, user_id)
    if not rows:
        return 0
    previous, upto_id = rows

    pending = await session_mod.messages_after(
        session_id, int(upto_id or 0), user_id=user_id
    )
    if len(pending) < SUMMARY_BATCH:
        return 0
    if ctx:
        await ctx.check_cancel()
        await ctx.update(progress=0.2, step="压缩会话记忆")

    to_summarize = pending[:-KEEP_RECENT]
    if len(to_summarize) > 60:
        # Fold large backlogs in bounded chunks; the next pass continues
        # from the new summary_upto_id without dropping messages.
        to_summarize = to_summarize[:60]
    if not to_summarize:
        return 0

    await ensure_token_budget(user_id=user_id)
    prompt = _PROMPT.format(
        previous=(previous or "（无）")[:MAX_SUMMARY_CHARS],
        conversation=_format_messages(
            [(r["role"], r["content"]) for r in to_summarize]
        ),
    )
    try:
        data = await llm_json(
            prompt,
            timeout=settings.llm_timeout,
            user_id=user_id,
            session_id=session_id,
            source="memory", purpose="utility",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("session_summary_failed", session=session_id, error=str(exc))
        return 0

    summary = _truncate(str(data.get("summary") or data.get("text") or ""))
    if not summary:
        return 0
    await session_mod.set_summary(session_id, summary, int(to_summarize[-1]["id"]))
    logger.info(
        "session_summary_written", session=session_id, messages=len(to_summarize)
    )
    return len(to_summarize)

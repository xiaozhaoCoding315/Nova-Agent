"""Daily memory layer: one compressed summary per user, scope and day."""
from datetime import date, datetime, time, timedelta, timezone

import structlog

from app.config import settings
from app.core.llm.json_call import llm_json
from app.core.memory import scope as scope_mod
from app.core.security.limits import ensure_token_budget
from app.core.security.redaction import redact_text
from app.db import execute, query

logger = structlog.get_logger()

DAILY_MIN_MESSAGES = 8
MAX_DAILY_LINES = 40
MAX_DAILY_CHARS = 2000

_PROMPT = """把下面这一天的对话压缩成一份供以后查阅的中文日摘要。
保留：目标、已确认的决策、技术约束、未完成事项、重要偏好与结论。
不要保留：寒暄、重复内容、大段代码、工具原始输出。
最多 40 行，直接输出 JSON：{{"summary": "..."}}

日期：{day}

对话：
{conversation}"""


def _truncate(text: str) -> str:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    return "\n".join(lines[:MAX_DAILY_LINES])[:MAX_DAILY_CHARS]


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=timezone.utc)
    return start, start + timedelta(days=1)


def _session_scope_filter(scope: scope_mod.Scope) -> tuple[str, list]:
    """Restrict source sessions to the scope being rolled up."""
    if scope.type == scope_mod.THESIS:
        return (
            "AND s.product_mode = 'thesis' AND s.thesis_project_id::text = %s",
            [scope.id],
        )
    if scope.type == scope_mod.REPO:
        return (
            "AND s.product_mode = 'dev' AND EXISTS ("
            "  SELECT 1 FROM session_repos sr "
            "  WHERE sr.session_id = s.id AND sr.repo_id::text = %s)",
            [scope.id],
        )
    if scope.type == scope_mod.GLOBAL:
        return "", []
    return "AND s.product_mode = 'dev'", []


async def _messages_for_day(
    user_id: int, day: date, scope: scope_mod.Scope
) -> list[tuple]:
    start, end = _day_bounds(day)
    scope_sql, scope_params = _session_scope_filter(scope)
    return await query(
        "SELECT m.role, m.content FROM messages m "
        "JOIN sessions s ON s.id = m.session_id "
        "WHERE s.user_id = %s AND m.created_at >= %s AND m.created_at < %s "
        f"{scope_sql} AND m.role IN ('user','assistant') ORDER BY m.id ASC LIMIT 400",
        (user_id, start, end, *scope_params),
    )


async def rollup_day(
    user_id: int,
    day: date | None = None,
    force: bool = False,
    ctx=None,
    scope_type: str = scope_mod.DEV,
    scope_id: str = "",
) -> int:
    """Generate one scope's daily summary if missing (0 = skipped)."""
    day = day or (date.today() - timedelta(days=1))
    scope = scope_mod.normalize(scope_type, scope_id)
    if not force:
        existing = await query(
            "SELECT 1 FROM memory_daily WHERE user_id = %s AND scope_type = %s "
            "AND scope_id = %s AND day = %s",
            (user_id, scope.type, scope.id, day),
        )
        if existing:
            return 0

    rows = await _messages_for_day(user_id, day, scope)
    if len(rows) < DAILY_MIN_MESSAGES:
        return 0
    if ctx:
        await ctx.check_cancel()

    await ensure_token_budget(user_id=user_id)
    conversation = "\n\n".join(
        f"{'用户' if role == 'user' else '助手'}: {redact_text((content or '').strip())[:1000]}"
        for role, content in rows
    )
    try:
        data = await llm_json(
            _PROMPT.format(day=day.isoformat(), conversation=conversation[:30000]),
            timeout=settings.llm_timeout,
            user_id=user_id,
            source="memory", purpose="utility",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("daily_summary_failed", user_id=user_id, day=str(day), error=str(exc))
        return 0

    summary = _truncate(str(data.get("summary") or data.get("text") or ""))
    if not summary:
        return 0
    await execute(
        "INSERT INTO memory_daily "
        "(user_id, day, summary, message_count, scope_type, scope_id) "
        "VALUES (%s, %s, %s, %s, %s, %s) "
        "ON CONFLICT (user_id, scope_type, scope_id, day) DO UPDATE SET "
        "summary = EXCLUDED.summary, message_count = EXCLUDED.message_count, "
        "updated_at = now()",
        (user_id, day, summary, len(rows), scope.type, scope.id),
    )
    logger.info(
        "daily_summary_written", user_id=user_id, day=str(day),
        scope=scope.type, messages=len(rows),
    )
    return len(rows)


async def rollup_yesterday(ctx=None) -> int:
    """Generate yesterday's summaries for each active product scope."""
    yesterday = date.today() - timedelta(days=1)
    start, end = _day_bounds(yesterday)
    rows = await query(
        "SELECT DISTINCT s.user_id, s.product_mode, "
        "COALESCE(s.thesis_project_id::text, '') "
        "FROM messages m JOIN sessions s ON s.id = m.session_id "
        "WHERE m.created_at >= %s AND m.created_at < %s",
        (start, end),
    )
    written = 0
    for user_id, product_mode, project_id in rows:
        mode = (product_mode or scope_mod.DEV).strip().lower()
        if mode == scope_mod.THESIS:
            if not project_id:
                continue
            scope_type, scope_id = scope_mod.THESIS, str(project_id)
        elif mode == scope_mod.DEV:
            scope_type, scope_id = scope_mod.DEV, ""
        else:
            continue
        written += 1 if await rollup_day(
            int(user_id), yesterday, ctx=ctx,
            scope_type=scope_type, scope_id=scope_id,
        ) else 0
    return written

"""Daily memory layer: one compressed summary per user, scope and day."""
import re
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
RECENT_DAILY_DAYS = 7

_RETROSPECTIVE = re.compile(
    r"(昨天|昨日|前天|上次|上一次|之前|此前|最近|那会儿|还记得|做到哪|"
    r"yesterday|last time|previously|last session|where were we)",
    re.IGNORECASE,
)

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


def is_retrospective(text: str) -> bool:
    """Questions about earlier work should see the episodic daily layer."""
    return bool(_RETROSPECTIVE.search(text or ""))


def _scope_filter(scopes: list[scope_mod.Scope] | None) -> tuple[str, list]:
    if scopes is None:
        return "", []
    if not scopes:
        return " AND FALSE", []
    parts: list[str] = []
    params: list = []
    for scope in scopes:
        parts.append("(scope_type = %s AND scope_id = %s)")
        params.extend([scope.type, scope.id])
    return " AND (" + " OR ".join(parts) + ")", params


async def recent_daily(
    user_id: int,
    scopes: list[scope_mod.Scope] | None,
    days: int = RECENT_DAILY_DAYS,
    limit: int = 5,
) -> list[dict]:
    """Recent daily summaries for the readable scopes, newest first."""
    since = date.today() - timedelta(days=max(1, int(days)))
    scope_sql, scope_params = _scope_filter(scopes)
    rows = await query(
        "SELECT day, summary, scope_type, scope_id FROM memory_daily "
        f"WHERE user_id = %s AND day >= %s {scope_sql} "
        "ORDER BY day DESC LIMIT %s",
        (user_id, since, *scope_params, max(1, int(limit))),
    )
    return [
        {
            "day": row[0].isoformat() if isinstance(row[0], date) else str(row[0]),
            "summary": row[1], "scope_type": row[2] or scope_mod.DEV,
            "scope_id": row[3] or "",
        }
        for row in rows
    ]


def format_daily_block(rows: list[dict]) -> str:
    """Compact prompt block for retrospective questions."""
    if not rows:
        return ""
    lines = []
    for row in rows:
        scope = scope_mod.normalize(row.get("scope_type"), row.get("scope_id"))
        lines.append(
            f"- {row.get('day', '')} · {scope.label}: "
            f"{(row.get('summary') or '').strip()[:600]}"
        )
    return (
        "\n\n## 近期日摘要（用户提到过去的工作，按时间倒序）\n"
        + "\n".join(lines)
    )


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
            "AND s.product_mode = 'dev' AND ("
            "  SELECT COUNT(*) FROM session_repos sr2 WHERE sr2.session_id = s.id"
            ") = 1 AND EXISTS ("
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

    # Single-repo sessions also get a repo-scoped daily summary, so a question
    # about this repository can retrieve its own episodic history.
    repo_rows = await query(
        "SELECT DISTINCT s.user_id, sr.repo_id::text "
        "FROM messages m JOIN sessions s ON s.id = m.session_id "
        "JOIN session_repos sr ON sr.session_id = s.id "
        "WHERE m.created_at >= %s AND m.created_at < %s "
        "AND s.product_mode = 'dev' AND ("
        "  SELECT COUNT(*) FROM session_repos sr2 WHERE sr2.session_id = s.id"
        ") = 1",
        (start, end),
    )
    for user_id, repo_id in repo_rows:
        written += 1 if await rollup_day(
            int(user_id), yesterday, ctx=ctx,
            scope_type=scope_mod.REPO, scope_id=str(repo_id),
        ) else 0
    return written

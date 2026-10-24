"""Reflection: turn outcome signals (retried tasks, rejected edits) into
short per-user lessons that are injected into later prompts.

Design rules:
- Lessons come from *results* (Gate retries, user rejections), never from
  model self-assessment.
- Deduped by (user, source); low-quality lessons age out automatically.
- Extraction runs in the hourly maintenance loop and is budget-guarded.
"""
import json
import uuid

import structlog

from app.core.llm.json_call import llm_json
from app.core.security.limits import ensure_token_budget
from app.db import execute, query

logger = structlog.get_logger()

MAX_LESSONS_PER_RUN = 6
MAX_LESSONS_IN_PROMPT = 5
LESSON_MAX_CHARS = 80


async def lessons_for_context(user_id: int, repo_ids: list[str]) -> list[dict]:
    """Top lessons for this user (repo-specific first), for prompt injection."""
    if not repo_ids:
        rows = await query(
            "SELECT id, kind, content FROM lessons WHERE user_id = %s AND repo_id IS NULL "
            "ORDER BY hits DESC, updated_at DESC LIMIT %s",
            (user_id, MAX_LESSONS_IN_PROMPT),
        )
    else:
        rows = await query(
            "SELECT id, kind, content FROM lessons WHERE user_id = %s "
            "AND (repo_id IS NULL OR repo_id = ANY(%s::uuid[])) "
            "ORDER BY (repo_id IS NOT NULL) DESC, hits DESC, updated_at DESC LIMIT %s",
            (user_id, repo_ids, MAX_LESSONS_IN_PROMPT),
        )
    return [
        {"id": str(r[0]), "kind": r[1], "content": r[2]} for r in rows
    ]


async def record_outcome(lesson_ids: list[str], ok: bool) -> None:
    """A turn that used these lessons finished: count hit or miss."""
    if not lesson_ids:
        return
    column = "hits = hits + 1, last_hit_at = now()" if ok else "misses = misses + 1"
    for lesson_id in lesson_ids:
        try:
            await execute(
                f"UPDATE lessons SET {column}, updated_at = now() WHERE id = %s",
                (lesson_id,),
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("lesson_outcome_failed", lesson=lesson_id, error=str(exc))


async def _already_known(user_id: int, source_type: str, source_id: str) -> bool:
    rows = await query(
        "SELECT 1 FROM lessons WHERE user_id = %s AND source_type = %s AND source_id = %s",
        (user_id, source_type, source_id),
    )
    return bool(rows)


async def _store_lesson(
    user_id: int, repo_id: str | None, source_type: str, source_id: str,
    kind: str, content: str,
) -> bool:
    content = (content or "").strip()[:LESSON_MAX_CHARS]
    kind = kind if kind in ("practice", "mistake") else "practice"
    if len(content) < 8:
        return False
    try:
        await execute(
            "INSERT INTO lessons (id, user_id, repo_id, kind, content, source_type, source_id) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
            (str(uuid.uuid4()), user_id, repo_id, kind, content, source_type, source_id),
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("lesson_store_failed", error=str(exc))
        return False


_PROMPT = """根据下面的开发事件，提炼一条给编码助手参考的经验教训。
要求：一句话、不超过 60 字、可执行（说清"该做什么/别做什么"），不要空话。

事件类型：{event_type}
{detail}

只输出 JSON：{{"kind": "practice 或 mistake", "content": "教训内容"}}"""


async def _extract_from_signal(
    user_id: int, repo_id: str | None, source_type: str, source_id: str,
    event_type: str, detail: str,
) -> bool:
    if await _already_known(user_id, source_type, source_id):
        return False
    try:
        await ensure_token_budget(user_id=user_id)
        data = await llm_json(
            _PROMPT.format(event_type=event_type, detail=detail[:2000]),
            user_id=user_id,
            source="reflection",
            purpose="utility",
        )
    except Exception as exc:  # noqa: BLE001
        logger.info("lesson_extract_failed", source=source_id, error=str(exc))
        return False
    return await _store_lesson(
        user_id, repo_id, source_type, source_id,
        str(data.get("kind") or ""), str(data.get("content") or ""),
    )


async def extract_lessons() -> dict:
    """Hourly maintenance entrypoint; guards included. Idempotent per source."""
    extracted = 0

    # 1) Change tasks that needed >=2 attempts before the Gate passed.
    rows = await query(
        """
        SELECT t.id, t.title, t.acceptance, t.result, c.user_id, t.repo_id
        FROM change_tasks t JOIN change_requests c ON c.id = t.request_id
        WHERE t.status = 'ready' AND t.attempts >= 2
          AND t.updated_at > now() - interval '2 days'
          AND c.user_id IS NOT NULL
        ORDER BY t.updated_at DESC LIMIT %s
        """,
        (MAX_LESSONS_PER_RUN,),
    )
    for task_id, title, acceptance, result, user_id, repo_id in rows:
        detail = f"任务：{title}\n验收：{acceptance}\n最终结果：{json.dumps(result or {}, ensure_ascii=False)[:1200]}"
        if await _extract_from_signal(
            user_id, str(repo_id) if repo_id else None,
            "change_task_retry", str(task_id),
            "任务第一次未通过验证门，重试后通过（第一次的方案有缺陷）", detail,
        ):
            extracted += 1

    # 2) Edit proposals the user explicitly rejected.
    rows = await query(
        """
        SELECT e.id, e.files, e.note, e.user_id, e.repo_id
        FROM edits e
        WHERE e.status = 'rejected' AND e.created_at > now() - interval '2 days'
        ORDER BY e.created_at DESC LIMIT %s
        """,
        (MAX_LESSONS_PER_RUN,),
    )
    for edit_id, files, note, user_id, repo_id in rows:
        detail = f"被拒绝的修改文件：{json.dumps(files or [], ensure_ascii=False)[:500]}\n说明：{note or '（无）'}"
        if await _extract_from_signal(
            user_id, str(repo_id) if repo_id else None,
            "edit_rejected", str(edit_id),
            "用户拒绝了助手生成的修改提案（方案不符合预期）", detail,
        ):
            extracted += 1

    await _forget_stale()
    if extracted:
        logger.info("lessons_extracted", count=extracted)
    return {"extracted": extracted}


async def _forget_stale() -> None:
    """Lessons that stopped helping or went stale are removed."""
    await execute(
        """
        DELETE FROM lessons WHERE
            (misses > hits AND updated_at < now() - interval '7 day')
            OR updated_at < now() - interval '30 day'
            OR (hits = 0 AND misses = 0 AND created_at < now() - interval '14 day')
        """
    )

"""User-visible memory: long-term facts and daily summaries."""
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response

from app.core.memory import facts as facts_mod
from app.core.memory import policy as policy_mod
from app.core.memory import scope as scope_mod
from app.core.security.audit import log_audit
from app.core.security.auth import get_current_user
from app.core.security.redaction import redact_text
from app.db import execute, query
from app.models.schemas import (
    MemoryFactCreate,
    MemoryFactCreateOut,
    MemoryFactOut,
    MemoryFactSourcesOut,
    MemoryFactUpdate,
    MemoryOut,
    MemoryPurgeOut,
    OkOut,
)

router = APIRouter()


@router.get("/memory", response_model=MemoryOut)
async def get_memory(
    scope_type: str | None = None,
    scope_id: str | None = None,
    status: str | None = None,
    include_inactive: bool = False,
    user: dict = Depends(get_current_user),
):
    fact_list = await facts_mod.list_facts(
        user["id"], scope_type=scope_type, scope_id=scope_id,
        status=status, include_inactive=include_inactive,
    )
    daily_scope_sql = ""
    daily_params: list = []
    if scope_type:
        scope = scope_mod.normalize(scope_type, scope_id)
        daily_scope_sql = " AND scope_type = %s AND scope_id = %s"
        daily_params = [scope.type, scope.id]
    daily = await query(
        "SELECT day, summary, message_count, created_at, updated_at, "
        "scope_type, scope_id FROM memory_daily "
        f"WHERE user_id = %s{daily_scope_sql} ORDER BY day DESC LIMIT 60",
        (user["id"], *daily_params),
    )
    return {
        "facts": fact_list,
        "daily": [
            {
                "day": r[0].isoformat() if isinstance(r[0], date) else str(r[0]),
                "summary": r[1], "message_count": int(r[2] or 0),
                "created_at": r[3], "updated_at": r[4],
                "scope_type": r[5] or "dev", "scope_id": r[6] or "",
            }
            for r in daily
        ],
    }


@router.post("/memory/facts", response_model=MemoryFactCreateOut)
async def create_fact(
    body: MemoryFactCreate, user: dict = Depends(get_current_user),
):
    sent = body.model_fields_set
    policy = await policy_mod.get_policy(user["id"])
    if "scope_type" in sent:
        scope = scope_mod.normalize(body.scope_type, body.scope_id)
    else:
        scope = scope_mod.normalize(policy.default_scope, "")
    if scope.type in (scope_mod.REPO, scope_mod.THESIS) and not scope.id:
        raise HTTPException(status_code=400, detail="该作用域需要 scope_id")
    ttl_days = body.ttl_days if "ttl_days" in sent else policy.retention_days
    added = await facts_mod.add_fact(
        user["id"], body.content,
        ttl_days=ttl_days, importance=body.importance,
        scope_type=scope.type, scope_id=scope.id,
        category=body.category, topic=body.topic,
    )
    return {"ok": True, "added": added}


@router.patch("/memory/facts/{fact_id}", response_model=MemoryFactOut)
async def update_fact(
    fact_id: int,
    body: MemoryFactUpdate,
    user: dict = Depends(get_current_user),
):
    try:
        updated = await facts_mod.edit_fact(
            user["id"], fact_id,
            content=body.content,
            importance=body.importance,
            ttl_days=body.ttl_days,
            category=body.category,
            status=body.status,
            topic=body.topic,
        )
    except facts_mod.FactDuplicateError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if updated is None:
        raise HTTPException(status_code=404, detail="记忆不存在")
    return updated


@router.get(
    "/memory/facts/{fact_id}/sources", response_model=MemoryFactSourcesOut,
)
async def get_fact_sources(
    fact_id: int, user: dict = Depends(get_current_user),
):
    sources = await facts_mod.fact_sources(user["id"], fact_id)
    if sources is None:
        raise HTTPException(status_code=404, detail="记忆不存在")
    return sources


@router.delete("/memory/facts/{fact_id}", response_model=OkOut)
async def delete_fact(fact_id: int, user: dict = Depends(get_current_user)):
    rows = await execute(
        "DELETE FROM facts WHERE id = %s AND user_id = %s RETURNING id",
        (fact_id, user["id"]),
    )
    if not rows:
        raise HTTPException(status_code=404, detail="记忆不存在")
    return {"ok": True}


@router.delete("/memory/daily/{day}", response_model=OkOut)
async def delete_daily(
    day: str,
    scope_type: str = "dev",
    scope_id: str = "",
    user: dict = Depends(get_current_user),
):
    try:
        parsed = date.fromisoformat(day)
    except ValueError:
        raise HTTPException(status_code=400, detail="日期格式应为 YYYY-MM-DD")
    scope = scope_mod.normalize(scope_type, scope_id)
    rows = await execute(
        "DELETE FROM memory_daily WHERE user_id = %s AND day = %s "
        "AND scope_type = %s AND scope_id = %s RETURNING day",
        (user["id"], parsed, scope.type, scope.id),
    )
    if not rows:
        raise HTTPException(status_code=404, detail="日摘要不存在")
    return {"ok": True}


async def _export_rows(user: dict, scope_type: str | None, scope_id: str | None):
    fact_list = await facts_mod.list_facts(
        user["id"], scope_type=scope_type, scope_id=scope_id,
        include_inactive=True, limit=5000,
    )
    daily_scope_sql = ""
    daily_params: list = []
    lesson_scope_sql = ""
    lesson_params: list = []
    if scope_type:
        scope = scope_mod.normalize(scope_type, scope_id)
        daily_scope_sql = " AND scope_type = %s AND scope_id = %s"
        daily_params = [scope.type, scope.id]
        if scope.type == scope_mod.REPO:
            lesson_scope_sql = " AND repo_id::text = %s"
            lesson_params = [scope.id]
    daily_rows = await query(
        "SELECT day, summary, message_count, created_at, updated_at, "
        "scope_type, scope_id FROM memory_daily "
        f"WHERE user_id = %s{daily_scope_sql} ORDER BY day DESC",
        (user["id"], *daily_params),
    )
    lessons = await query(
        "SELECT kind, content, created_at FROM lessons WHERE user_id = %s"
        f"{lesson_scope_sql} ORDER BY created_at DESC",
        (user["id"], *lesson_params),
    )
    return {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "facts": fact_list,
        "daily": [
            {
                "day": row[0].isoformat() if isinstance(row[0], date) else str(row[0]),
                "summary": redact_text(row[1]), "message_count": int(row[2] or 0),
                "created_at": row[3], "updated_at": row[4],
                "scope_type": row[5] or scope_mod.DEV, "scope_id": row[6] or "",
            }
            for row in daily_rows
        ],
        "lessons": [
            {
                "kind": row[0], "content": redact_text(row[1]),
                "created_at": row[2],
            }
            for row in lessons
        ],
    }


def _export_markdown(payload: dict) -> str:
    lines = ["# Nova Agent 记忆导出", "", f"导出时间：{payload['exported_at']}", ""]
    lines.append("## 长期事实")
    if not payload["facts"]:
        lines.append("（无）")
    for fact in payload["facts"]:
        scope = scope_mod.normalize(fact.get("scope_type"), fact.get("scope_id"))
        lines.append(
            f"### #{fact['id']} · {scope.label} · {fact.get('category', 'fact')}"
            f" · {fact.get('status', 'active')} · v{fact.get('version', 1)}"
        )
        lines.append(redact_text(fact.get("content") or ""))
        source = []
        if fact.get("source_session_id"):
            source.append(f"会话 {fact['source_session_id']}")
        if fact.get("source_message_id"):
            source.append(f"消息 {fact['source_message_id']}")
        if fact.get("supersedes_id"):
            source.append(f"替代 #{fact['supersedes_id']}")
        if fact.get("merged_into_id"):
            source.append(f"已合并到 #{fact['merged_into_id']}")
        if source:
            lines.append(f"- 来源：{'；'.join(source)}")
        lines.append("")
    lines.append("## 日摘要")
    if not payload["daily"]:
        lines.append("（无）")
    for item in payload["daily"]:
        scope = scope_mod.normalize(item.get("scope_type"), item.get("scope_id"))
        lines.append(f"### {item['day']} · {scope.label}")
        lines.append(redact_text(item.get("summary") or ""))
        lines.append("")
    lines.append("## 经验教训")
    if not payload["lessons"]:
        lines.append("（无）")
    for item in payload["lessons"]:
        lines.append(f"- [{item.get('kind')}] {redact_text(item.get('content') or '')}")
    return "\n".join(lines) + "\n"


@router.get("/memory/export")
async def export_memory(
    format: str = "json",
    scope_type: str | None = None,
    scope_id: str | None = None,
    user: dict = Depends(get_current_user),
):
    fmt = (format or "json").strip().lower()
    if fmt in ("md",):
        fmt = "markdown"
    if fmt not in ("json", "markdown"):
        raise HTTPException(status_code=400, detail="format 只支持 json 或 markdown")
    if scope_type and scope_type not in scope_mod.VALID_TYPES:
        raise HTTPException(status_code=400, detail="无效的作用域")
    payload = await _export_rows(user, scope_type, scope_id)
    await log_audit(
        "memory_export", user_id=str(user["id"]),
        details={
            "format": fmt, "scope": scope_type or "all",
            "facts": len(payload["facts"]), "daily": len(payload["daily"]),
        },
    )
    if fmt == "json":
        return payload
    return Response(
        content=_export_markdown(payload),
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="nova-memory.md"',
        },
    )


@router.delete("/memory/all", response_model=MemoryPurgeOut)
async def delete_all_memory(
    confirm: bool = False,
    scope_type: str | None = None,
    scope_id: str = "",
    include_messages: bool = True,
    user: dict = Depends(get_current_user),
):
    if not confirm:
        raise HTTPException(status_code=400, detail="需要 confirm=true 才能删除")
    counts: dict[str, int] = {}
    if scope_type:
        if scope_type not in scope_mod.VALID_TYPES:
            raise HTTPException(status_code=400, detail="无效的作用域")
        scope = scope_mod.normalize(scope_type, scope_id)
        if scope.type in (scope_mod.REPO, scope_mod.THESIS) and not scope.id:
            raise HTTPException(status_code=400, detail="该作用域需要 scope_id")
        facts_removed = await execute(
            "DELETE FROM facts WHERE user_id = %s AND scope_type = %s "
            "AND scope_id = %s RETURNING id",
            (user["id"], scope.type, scope.id),
        )
        daily_removed = await execute(
            "DELETE FROM memory_daily WHERE user_id = %s AND scope_type = %s "
            "AND scope_id = %s RETURNING day",
            (user["id"], scope.type, scope.id),
        )
        lessons_removed = []
        if scope.type == scope_mod.REPO:
            lessons_removed = await execute(
                "DELETE FROM lessons WHERE user_id = %s AND repo_id::text = %s "
                "RETURNING id",
                (user["id"], scope.id),
            )
        counts.update(
            facts=len(facts_removed or []),
            daily=len(daily_removed or []),
            lessons=len(lessons_removed or []),
            messages=0,
        )
    else:
        facts_removed = await execute(
            "DELETE FROM facts WHERE user_id = %s RETURNING id", (user["id"],),
        )
        daily_removed = await execute(
            "DELETE FROM memory_daily WHERE user_id = %s RETURNING day",
            (user["id"],),
        )
        lessons_removed = await execute(
            "DELETE FROM lessons WHERE user_id = %s RETURNING id", (user["id"],),
        )
        await execute(
            "DELETE FROM compaction_records WHERE session_id IN "
            "(SELECT id FROM sessions WHERE user_id = %s)",
            (user["id"],),
        )
        messages_removed = []
        if include_messages:
            messages_removed = await execute(
                "DELETE FROM messages WHERE session_id IN "
                "(SELECT id FROM sessions WHERE user_id = %s) RETURNING id",
                (user["id"],),
            )
        await execute(
            "UPDATE sessions SET summary = '', summary_upto_id = 0 "
            "WHERE user_id = %s",
            (user["id"],),
        )
        counts.update(
            facts=len(facts_removed or []),
            daily=len(daily_removed or []),
            lessons=len(lessons_removed or []),
            messages=len(messages_removed or []),
        )
    await log_audit(
        "memory_purge", user_id=str(user["id"]),
        details={"scope": scope_type or "all", **counts},
    )
    return {"ok": True, **counts}

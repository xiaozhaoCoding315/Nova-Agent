"""User-visible memory: long-term facts and daily summaries."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException

from app.core.memory import facts as facts_mod
from app.core.memory import scope as scope_mod
from app.core.security.auth import get_current_user
from app.db import execute, query
from app.models.schemas import (
    MemoryFactCreate,
    MemoryFactCreateOut,
    MemoryFactOut,
    MemoryFactSourcesOut,
    MemoryFactUpdate,
    MemoryOut,
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
    scope = scope_mod.normalize(body.scope_type, body.scope_id)
    if scope.type in (scope_mod.REPO, scope_mod.THESIS) and not scope.id:
        raise HTTPException(status_code=400, detail="该作用域需要 scope_id")
    added = await facts_mod.add_fact(
        user["id"], body.content,
        ttl_days=body.ttl_days, importance=body.importance,
        scope_type=scope.type, scope_id=scope.id,
        category=body.category,
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

"""User-visible memory: long-term facts and daily summaries."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException

from app.core.security.auth import get_current_user
from app.db import execute, query
from app.models.schemas import MemoryOut, OkOut

router = APIRouter()


@router.get("/memory", response_model=MemoryOut)
async def get_memory(user: dict = Depends(get_current_user)):
    facts = await query(
        "SELECT id, content, importance, ttl_days, promoted_at, last_used_at, created_at "
        "FROM facts WHERE user_id = %s ORDER BY importance DESC, last_used_at DESC LIMIT 200",
        (user["id"],),
    )
    daily = await query(
        "SELECT day, summary, message_count, created_at, updated_at FROM memory_daily "
        "WHERE user_id = %s ORDER BY day DESC LIMIT 60",
        (user["id"],),
    )
    return {
        "facts": [
            {
                "id": r[0], "content": r[1], "importance": float(r[2] or 1.0),
                "ttl_days": int(r[3] or 90), "promoted_at": r[4],
                "last_used_at": r[5], "created_at": r[6],
            }
            for r in facts
        ],
        "daily": [
            {
                "day": r[0].isoformat() if isinstance(r[0], date) else str(r[0]),
                "summary": r[1], "message_count": int(r[2] or 0),
                "created_at": r[3], "updated_at": r[4],
            }
            for r in daily
        ],
    }


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
async def delete_daily(day: str, user: dict = Depends(get_current_user)):
    try:
        parsed = date.fromisoformat(day)
    except ValueError:
        raise HTTPException(status_code=400, detail="日期格式应为 YYYY-MM-DD")
    rows = await execute(
        "DELETE FROM memory_daily WHERE user_id = %s AND day = %s RETURNING day",
        (user["id"], parsed),
    )
    if not rows:
        raise HTTPException(status_code=404, detail="日摘要不存在")
    return {"ok": True}

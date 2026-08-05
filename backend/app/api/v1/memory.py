from fastapi import APIRouter
from app.core.memory import (
    get_summary, get_facts, clear_facts, extract_facts,
    add_message, get_history, clear_session,
    save_fact, run_ttl_cleanup, get_stats,
    dedup_facts, get_user_profile, get_profile_summary,
    archive_session,
)
from app.core.memory.session import get_or_create_session

router = APIRouter()


@router.get("/memory/{session_id}")
async def get_memory_summary(session_id: str):
    summary = get_summary(session_id)
    facts = await get_facts(session_id, limit=10)
    profile = await get_user_profile()
    stats = await get_stats()
    return {**summary, "facts": facts, "profile": profile, "stats": stats}


@router.get("/memory/{session_id}/profile")
async def get_profile(session_id: str):
    profile = await get_user_profile()
    summary_text = await get_profile_summary()
    return {"profile": profile, "summary": summary_text}


@router.post("/memory/{session_id}/extract")
async def trigger_extraction(session_id: str):
    history = get_history(session_id, last_n=20)
    if len(history) < 2:
        return {"extracted": 0, "message": "Not enough messages"}
    raw_facts = await extract_facts(history)
    facts = await dedup_facts(raw_facts, session_id)
    for f in facts:
        await save_fact(session_id, f["fact"], f.get("category", "general"))
    return {"extracted": len(facts), "facts": facts}


@router.post("/memory/{session_id}/archive")
async def trigger_archive(session_id: str):
    """Archive session facts to persistent memory."""
    result = await archive_session(session_id)
    return result


@router.delete("/memory/{session_id}")
async def clear_memory(session_id: str):
    clear_session(session_id)
    await clear_facts(session_id)
    return {"status": "ok", "cleared": session_id}


@router.get("/memory/stats/overview")
async def memory_stats():
    """Get memory system statistics."""
    return await get_stats()


@router.post("/memory/maintenance/cleanup")
async def trigger_cleanup():
    """Run TTL cleanup job."""
    deleted = await run_ttl_cleanup()
    return {"deleted": deleted, "status": "ok"}

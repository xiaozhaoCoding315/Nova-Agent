"""Chat endpoints: session CRUD + SSE message stream + edit approvals."""
import asyncio
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.core.agent.loop import run_chat
from app.core.conflicts import ConflictError
from app.core.editing.service import apply_edit, get_edit, reject_edit, revert_edit
from app.core.indexing.pipeline import get_repo, reindex_repo
from app.core.memory import session as session_mod
from app.core.review.service import review_edit as review_edit_service
from app.core.security.auth import get_current_user
from app.core.security.limits import check_chat_quota, check_job_quota
from app.core.trace import list_events, record as trace_record
from app.db import execute
from app.models.schemas import ChatRequest, MessageOut, SessionOut

router = APIRouter()


@router.get("/chat/sessions", response_model=list[SessionOut])
async def list_sessions(user: dict = Depends(get_current_user)):
    return await session_mod.list_sessions(user["id"])


@router.post("/chat/sessions", response_model=SessionOut)
async def create_session(user: dict = Depends(get_current_user)):
    session = await session_mod.create_session(user["id"])
    return {"id": session["id"], "title": session["title"], "message_count": 0}


@router.get("/chat/sessions/{session_id}/messages", response_model=list[MessageOut])
async def get_session_messages(session_id: str, user: dict = Depends(get_current_user)):
    session = await session_mod.get_session(session_id, user["id"])
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    return await session_mod.get_messages(session_id)


@router.delete("/chat/sessions/{session_id}")
async def delete_session(session_id: str, user: dict = Depends(get_current_user)):
    if not await session_mod.delete_session(session_id, user["id"]):
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"ok": True}


@router.post("/chat/message")
async def chat_message(
    body: ChatRequest,
    request: Request,
    user: dict = Depends(get_current_user),
):
    await check_chat_quota(user)

    if body.session_id:
        session = await session_mod.get_session(body.session_id, user["id"])
        if not session:
            raise HTTPException(status_code=404, detail="会话不存在")
    else:
        session = await session_mod.create_session(user["id"])

    if body.permission_mode and body.permission_mode != session.get("permission_mode"):
        await execute(
            "UPDATE sessions SET permission_mode = %s WHERE id = %s",
            (body.permission_mode, session["id"]),
        )
        session["permission_mode"] = body.permission_mode

    effective_repo_ids = (
        body.repo_ids if body.repo_ids is not None else (session.get("repo_ids") or [])
    )
    effective_repo_ids = list(dict.fromkeys(effective_repo_ids))[:5]
    for repo_id in effective_repo_ids:
        if not await get_repo(repo_id, user["id"]):
            raise HTTPException(status_code=404, detail=f"仓库不存在或无权访问：{repo_id}")
    if body.repo_ids is not None:
        await session_mod.set_repo_ids(session["id"], effective_repo_ids)
        session["repo_ids"] = effective_repo_ids

    await session_mod.add_message(session["id"], "user", body.content)
    session["title"] = await session_mod.maybe_set_title(session["id"], body.content)
    turn_id = str(uuid.uuid4())
    await trace_record(session["id"], turn_id, "user", {
        "content": body.content[:4000],
        "repo_ids": effective_repo_ids,
        "permission_mode": session.get("permission_mode", "ask"),
    })

    generator = run_chat(user, session, body.content, effective_repo_ids, turn_id=turn_id)

    async def event_stream():
        try:
            async for event in generator:
                if await request.is_disconnected():
                    break
                data = json.dumps(event["data"], ensure_ascii=False, default=str)
                yield f"event: {event['event']}\ndata: {data}\n\n"
        except Exception as exc:  # noqa: BLE001
            payload = json.dumps(
                {"code": "internal", "message": f"服务内部错误：{exc}"}, ensure_ascii=False
            )
            yield f"event: error\ndata: {payload}\n\n"
        finally:
            # Deterministic close so a client "stop" still persists partial output.
            await generator.aclose()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/chat/sessions/{session_id}/trajectory")
async def session_trajectory(
    session_id: str,
    limit: int = 500,
    user: dict = Depends(get_current_user),
):
    session = await session_mod.get_session(session_id, user["id"])
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    return await list_events(session_id, min(max(limit, 1), 1000))


# ---------- Edit proposals (in-chat file changes) ----------

@router.get("/edits/{edit_id}")
async def get_edit_endpoint(edit_id: str, user: dict = Depends(get_current_user)):
    edit = await get_edit(edit_id, user["id"])
    if not edit:
        raise HTTPException(status_code=404, detail="修改不存在")
    return edit


@router.post("/edits/{edit_id}/approve")
async def approve_edit_endpoint(edit_id: str, user: dict = Depends(get_current_user)):
    check_job_quota(user, "reindex")
    try:
        result = await apply_edit(edit_id, user["id"])
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if result.get("session_id"):
        await trace_record(result["session_id"], str(uuid.uuid4()), "edit_applied", {
            "edit_id": edit_id, "repo_id": result["repo_id"], "files": result["applied"],
            "commit": result.get("commit"),
        })
    asyncio.create_task(reindex_repo(result["repo_id"]))
    return {"ok": True, "applied": result["applied"],
            "commit": result.get("commit"), "reindex_started": True}


@router.post("/edits/{edit_id}/review")
async def review_edit_endpoint(edit_id: str, user: dict = Depends(get_current_user)):
    if not await get_edit(edit_id, user["id"]):
        raise HTTPException(status_code=404, detail="修改不存在")
    check_job_quota(user, "review")
    try:
        return await review_edit_service(edit_id, user["id"])
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"审查失败：{exc}")


@router.post("/edits/{edit_id}/reject")
async def reject_edit_endpoint(edit_id: str, user: dict = Depends(get_current_user)):
    try:
        info = await reject_edit(edit_id, user["id"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if info.get("session_id"):
        await trace_record(info["session_id"], str(uuid.uuid4()), "edit_rejected", {
            "edit_id": edit_id, "repo_id": info["repo_id"],
        })
    return {"ok": True}


@router.post("/edits/{edit_id}/revert")
async def revert_edit_endpoint(edit_id: str, user: dict = Depends(get_current_user)):
    check_job_quota(user, "reindex")
    try:
        result = await revert_edit(edit_id, user["id"])
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if result.get("session_id"):
        await trace_record(result["session_id"], str(uuid.uuid4()), "edit_reverted", {
            "edit_id": edit_id, "repo_id": result["repo_id"],
            "restored": result.get("restored"), "removed": result.get("removed"),
            "commit": result.get("commit"),
        })
    asyncio.create_task(reindex_repo(result["repo_id"]))
    return {"ok": True, **result, "reindex_started": True}
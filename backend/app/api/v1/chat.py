"""Chat endpoints: session CRUD + SSE message stream + edit approvals."""
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.core.agent.loop import run_chat
from app.core.conflicts import ConflictError
from app.core.editing.service import apply_edit, get_edit, reject_edit, revert_edit
from app.core.indexing.pipeline import get_repo
from app.core.jobs.service import enqueue_index
from app.core.memory import session as session_mod
from app.core.review.service import review_edit as review_edit_service
from app.core.security.auth import get_current_user
from app.core.security.limits import check_chat_quota, check_job_quota
from app.core.trace import list_events, record as trace_record
from app.db import execute
from app.models.schemas import (
    ChatRequest,
    EditApproveOut,
    EditOut,
    EditRevertOut,
    MessageOut,
    OkOut,
    ReviewOut,
    SessionCreateRequest,
    SessionOut,
    SessionRenameRequest,
    TraceEventOut,
)

router = APIRouter()


@router.get("/chat/sessions", response_model=list[SessionOut])
async def list_sessions(
    repo_id: str | None = Query(default=None),
    user: dict = Depends(get_current_user),
):
    return await session_mod.list_sessions(user["id"], repo_id=repo_id)


@router.post("/chat/sessions", response_model=SessionOut)
async def create_session(
    body: SessionCreateRequest | None = None,
    user: dict = Depends(get_current_user),
):
    repo_ids = list(dict.fromkeys((body.repo_ids if body else []) or []))[:5]
    for repo_id in repo_ids:
        if not await get_repo(repo_id, user["id"]):
            raise HTTPException(status_code=404, detail=f"仓库不存在或无权访问：{repo_id}")
    session = await session_mod.create_session(user["id"], repo_ids=repo_ids)
    return {
        "id": session["id"], "title": session["title"], "message_count": 0,
        "repo_ids": repo_ids,
        "primary_repo_id": repo_ids[0] if repo_ids else None,
        "model": session.get("model"),
    }


@router.get("/chat/sessions/{session_id}/messages", response_model=list[MessageOut])
async def get_session_messages(session_id: str, user: dict = Depends(get_current_user)):
    session = await session_mod.get_session(session_id, user["id"])
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    return await session_mod.get_messages(session_id)


@router.patch("/chat/sessions/{session_id}", response_model=SessionOut)
async def rename_session(
    session_id: str,
    body: SessionRenameRequest,
    user: dict = Depends(get_current_user),
):
    session = await session_mod.get_session(session_id, user["id"])
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="会话标题不能为空")
    renamed = await session_mod.rename_session(session_id, user["id"], title)
    if not renamed:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {
        "id": renamed["id"], "title": renamed["title"],
        "message_count": await session_mod.count_messages(session_id),
        "permission_mode": session.get("permission_mode", "ask"),
        "repo_ids": session.get("repo_ids", []),
        "primary_repo_id": session.get("primary_repo_id"),
        "model": session.get("model"),
        "created_at": renamed["created_at"], "updated_at": renamed["updated_at"],
    }


@router.delete("/chat/sessions/{session_id}", response_model=OkOut)
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
        session = await session_mod.create_session(user["id"], model=body.model)

    if body.model and body.model.strip() != (session.get("model") or ""):
        model = body.model.strip()
        await execute("UPDATE sessions SET model = %s WHERE id = %s", (model, session["id"]))
        session["model"] = model

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
        try:
            await session_mod.set_repo_ids(
                session["id"], effective_repo_ids, user_id=user["id"]
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        session["repo_ids"] = effective_repo_ids
        session["primary_repo_id"] = effective_repo_ids[0] if effective_repo_ids else None

    await session_mod.add_message(session["id"], "user", body.content)
    session["title"] = await session_mod.maybe_set_title(session["id"], body.content)
    turn_id = str(uuid.uuid4())
    await trace_record(session["id"], turn_id, "user", {
        "content": body.content[:4000],
        "repo_ids": effective_repo_ids,
        "permission_mode": session.get("permission_mode", "ask"),
        "model": session.get("model"),
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


@router.get("/chat/sessions/{session_id}/trajectory", response_model=list[TraceEventOut])
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

@router.get("/edits/{edit_id}", response_model=EditOut)
async def get_edit_endpoint(edit_id: str, user: dict = Depends(get_current_user)):
    edit = await get_edit(edit_id, user["id"])
    if not edit:
        raise HTTPException(status_code=404, detail="修改不存在")
    return edit


@router.post("/edits/{edit_id}/approve", response_model=EditApproveOut)
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
    await enqueue_index(result["repo_id"], reindex=True, user_id=user["id"])
    return {"ok": True, "applied": result["applied"],
            "commit": result.get("commit"), "reindex_started": True}


@router.post("/edits/{edit_id}/review", response_model=ReviewOut)
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


@router.post("/edits/{edit_id}/reject", response_model=OkOut)
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


@router.post("/edits/{edit_id}/revert", response_model=EditRevertOut)
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
    await enqueue_index(result["repo_id"], reindex=True, user_id=user["id"])
    return {"ok": True, **result, "reindex_started": True}
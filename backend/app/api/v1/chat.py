"""Chat endpoints: session CRUD + SSE message stream + edit approvals."""
import asyncio
import contextlib
import time
import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.core.conflicts import ConflictError
from app.core.editing.service import apply_edit, get_edit, reject_edit, revert_edit
from app.core.indexing.pipeline import get_repo
from app.core.jobs import service as jobs_service
from app.core.jobs.service import enqueue_index
from app.core.memory import session as session_mod
from app.core.review.service import review_edit as review_edit_service
from app.core.security.auth import get_current_user
from app.core.security.limits import check_chat_quota, check_job_quota
from app.core.storage.user_storage import get_file
from app.core.trace import list_events, record as trace_record
from app.core.turns import events as turn_events
from app.core.turns import service as turn_service
from app.core.turns import store as turn_store
from app.db import execute
from app.models.schemas import (
    ActiveTurnOut,
    ChatRequest,
    EditApproveOut,
    EditOut,
    EditRevertOut,
    MessageOut,
    OkOut,
    ReviewOut,
    SessionCreateRequest,
    SessionOut,
    SessionUpdateRequest,
    TraceEventOut,
    TurnCancelOut,
    TurnOut,
)

router = APIRouter()
logger = structlog.get_logger()

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


async def _tail_turn(turn_id: str, request: Request, after_seq: int = 0):
    last_seq = max(int(after_seq), 0)
    turn = await turn_store.get_turn(turn_id)
    yield turn_events.sse_frame("turn", {
        "turn_id": turn_id,
        "session_id": turn["session_id"] if turn else None,
        "status": turn["status"] if turn else "missing",
    })
    last_keepalive = time.monotonic()
    while True:
        rows = await turn_events.load_events(turn_id, last_seq)
        for row in rows:
            last_seq = row["seq"]
            yield turn_events.sse_frame(row["type"], row["payload"] or {})
        turn = await turn_store.get_turn(turn_id)
        if not turn:
            break
        if turn["status"] not in turn_store.ACTIVE_STATUSES:
            # Terminal status is written after the final event; keep reading
            # until the log is exhausted so long replays are never truncated.
            while True:
                rows = await turn_events.load_events(turn_id, last_seq)
                if not rows:
                    break
                for row in rows:
                    last_seq = row["seq"]
                    yield turn_events.sse_frame(row["type"], row["payload"] or {})
            break
        if await request.is_disconnected():
            break
        now = time.monotonic()
        if now - last_keepalive >= 15:
            last_keepalive = now
            yield ": keepalive\n\n"
        if not rows:
            await asyncio.sleep(0.25)


def _session_payload(session: dict, message_count: int = 0) -> dict:
    return {
        "id": session["id"],
        "title": session["title"],
        "message_count": message_count,
        "permission_mode": session.get("permission_mode", "ask"),
        "repo_ids": session.get("repo_ids", []),
        "primary_repo_id": session.get("primary_repo_id"),
        "model": session.get("model"),
        "llm_overrides": session.get("llm_overrides") or {},
        "created_at": session.get("created_at"),
        "updated_at": session.get("updated_at"),
    }


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
    overrides = (
        body.llm_overrides.model_dump(exclude_none=True)
        if body and body.llm_overrides else {}
    )
    session = await session_mod.create_session(
        user["id"], repo_ids=repo_ids, llm_overrides=overrides,
    )
    return _session_payload(session)


@router.get("/chat/sessions/{session_id}/messages", response_model=list[MessageOut])
async def get_session_messages(session_id: str, user: dict = Depends(get_current_user)):
    session = await session_mod.get_session(session_id, user["id"])
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    return await session_mod.get_messages(session_id, user_id=user["id"])


@router.patch("/chat/sessions/{session_id}", response_model=SessionOut)
async def update_session(
    session_id: str,
    body: SessionUpdateRequest,
    user: dict = Depends(get_current_user),
):
    session = await session_mod.get_session(session_id, user["id"])
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    if body.title is not None:
        title = body.title.strip()
        if not title:
            raise HTTPException(status_code=400, detail="会话标题不能为空")
        renamed = await session_mod.rename_session(session_id, user["id"], title)
        if not renamed:
            raise HTTPException(status_code=404, detail="会话不存在")

    if body.llm_overrides is not None:
        merged = await session_mod.update_llm_overrides(
            session_id, user["id"], body.llm_overrides.model_dump(exclude_none=True),
        )
        session["llm_overrides"] = merged or {}

    fresh = await session_mod.get_session(session_id, user["id"])
    if not fresh:
        raise HTTPException(status_code=404, detail="会话不存在")
    return _session_payload(fresh, await session_mod.count_messages(session_id))


@router.delete("/chat/sessions/{session_id}", response_model=OkOut)
async def delete_session(session_id: str, user: dict = Depends(get_current_user)):
    session = await session_mod.get_session(session_id, user["id"])
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    active = await turn_store.get_active_turn(session_id, user["id"])
    if active:
        await turn_store.request_cancel(active["id"])
        if active.get("job_id"):
            from app.core.jobs.runner import runner
            with contextlib.suppress(Exception):
                await runner.cancel(str(active["job_id"]), user["id"])
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

    incoming_overrides = (
        body.llm_overrides.model_dump(exclude_none=True)
        if body.llm_overrides else None
    )
    if body.session_id:
        session = await session_mod.get_session(body.session_id, user["id"])
        if not session:
            raise HTTPException(status_code=404, detail="会话不存在")
        if incoming_overrides is not None:
            merged = await session_mod.update_llm_overrides(
                session["id"], user["id"], incoming_overrides,
            )
            session["llm_overrides"] = merged or {}
    else:
        session = await session_mod.create_session(
            user["id"], model=body.model, llm_overrides=incoming_overrides,
        )

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

    attachments: list[dict] = []
    for file_id in list(dict.fromkeys(body.file_ids))[:5]:
        file = await get_file(file_id, user["id"])
        if not file:
            raise HTTPException(status_code=404, detail=f"附件不存在或无权访问：{file_id}")
        attachments.append({
            "id": file["id"], "filename": file["filename"],
            "mime": file["mime"], "size": file["size"],
        })

    active = await turn_store.get_active_turn(session["id"], user["id"])
    if active:
        raise HTTPException(
            status_code=409, detail="上一条消息仍在执行，请等待完成或停止后再发送",
        )

    user_message_id = await session_mod.add_message(
        session["id"], "user", body.content, attachments=attachments
    )
    session["title"] = await session_mod.maybe_set_title(session["id"], body.content)
    turn_id = str(uuid.uuid4())
    await trace_record(session["id"], turn_id, "user", {
        "content": body.content[:4000],
        "repo_ids": effective_repo_ids,
        "permission_mode": session.get("permission_mode", "ask"),
        "model": session.get("model"),
        "llm_overrides": session.get("llm_overrides") or {},
        "file_ids": [item["id"] for item in attachments],
    })

    turn = await turn_store.create_turn(
        turn_id, session["id"], user["id"], user_message_id,
    )
    if not turn:
        await execute(
            "DELETE FROM messages WHERE id = %s AND role = 'user'",
            (user_message_id,),
        )
        raise HTTPException(
            status_code=409, detail="上一条消息仍在执行，请等待完成或停止后再发送",
        )

    job_id = None
    try:
        job_id = await jobs_service.enqueue_chat_turn(
            turn_id, session["id"], user["id"],
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("chat_turn_enqueue_failed", error=str(exc))
    if job_id:
        await turn_store.set_job_id(turn_id, job_id)
    else:
        turn_service.start_turn_task(turn_id)

    return StreamingResponse(
        _tail_turn(turn_id, request),
        media_type="text/event-stream",
        headers={
            **_SSE_HEADERS,
            "X-Turn-Id": turn_id,
            "X-Session-Id": session["id"],
        },
    )


@router.get("/chat/turns/{turn_id}", response_model=TurnOut)
async def get_turn_status(turn_id: str, user: dict = Depends(get_current_user)):
    turn = await turn_store.get_turn(turn_id, user["id"])
    if not turn:
        raise HTTPException(status_code=404, detail="回合不存在")
    return turn


@router.get("/chat/turns/{turn_id}/stream")
async def stream_turn(
    turn_id: str,
    request: Request,
    after_seq: int = Query(default=0, ge=0),
    user: dict = Depends(get_current_user),
):
    turn = await turn_store.get_turn(turn_id, user["id"])
    if not turn:
        raise HTTPException(status_code=404, detail="回合不存在")
    return StreamingResponse(
        _tail_turn(turn_id, request, after_seq),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


@router.post("/chat/turns/{turn_id}/cancel", response_model=TurnCancelOut)
async def cancel_turn(turn_id: str, user: dict = Depends(get_current_user)):
    turn = await turn_store.get_turn(turn_id, user["id"])
    if not turn:
        raise HTTPException(status_code=404, detail="回合不存在")
    if turn["status"] not in turn_store.ACTIVE_STATUSES:
        return {"ok": True, "canceled": False}
    updated = await turn_store.request_cancel(turn_id)
    if turn.get("job_id"):
        from app.core.jobs.runner import runner
        with contextlib.suppress(Exception):
            await runner.cancel(str(turn["job_id"]), user["id"])
    return {"ok": True, "canceled": bool(updated)}


@router.get(
    "/chat/sessions/{session_id}/turns/active", response_model=ActiveTurnOut,
)
async def active_turn(session_id: str, user: dict = Depends(get_current_user)):
    if not await session_mod.get_session(session_id, user["id"]):
        raise HTTPException(status_code=404, detail="会话不存在")
    return {
        "turn": await turn_store.get_active_turn(session_id, user["id"]),
        "latest": await turn_store.get_latest_turn(session_id, user["id"]),
    }


@router.post("/chat/sessions/{session_id}/tools/{tool_call_id}/cancel")
async def cancel_tool(
    session_id: str,
    tool_call_id: str,
    user: dict = Depends(get_current_user),
):
    """Kill the sandbox container labelled with the in-flight tool call."""
    session = await session_mod.get_session(session_id, user["id"])
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    from app.core.sandbox.runtime import kill_job_containers
    killed = await kill_job_containers(tool_call_id, user["id"])
    return {"ok": True, "killed": killed}


@router.post("/chat/sessions/{session_id}/tools/{tool_call_id}/approve")
async def approve_tool(
    session_id: str,
    tool_call_id: str,
    user: dict = Depends(get_current_user),
):
    session = await session_mod.get_session(session_id, user["id"])
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    from app.core import approvals
    if not approvals.resolve(session_id, tool_call_id, user["id"], True):
        raise HTTPException(status_code=409, detail="审批已过期或不存在")
    return {"ok": True, "approved": True}


@router.post("/chat/sessions/{session_id}/tools/{tool_call_id}/reject")
async def reject_tool(
    session_id: str,
    tool_call_id: str,
    user: dict = Depends(get_current_user),
):
    session = await session_mod.get_session(session_id, user["id"])
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    from app.core import approvals
    if not approvals.resolve(session_id, tool_call_id, user["id"], False):
        raise HTTPException(status_code=409, detail="审批已过期或不存在")
    return {"ok": True, "approved": False}


@router.get("/chat/sessions/{session_id}/trajectory", response_model=list[TraceEventOut])
async def session_trajectory(
    session_id: str,
    limit: int = 500,
    user: dict = Depends(get_current_user),
):
    session = await session_mod.get_session(session_id, user["id"])
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    return await list_events(session_id, min(max(limit, 1), 1000), user_id=user["id"])


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
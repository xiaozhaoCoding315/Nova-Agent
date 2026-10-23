"""Chat endpoints: session CRUD + SSE message stream."""
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.core.agent.loop import run_chat
from app.core.memory import session as session_mod
from app.core.security.auth import get_current_user
from app.core.security.limits import check_chat_quota
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

    await session_mod.add_message(session["id"], "user", body.content)
    session["title"] = await session_mod.maybe_set_title(session["id"], body.content)

    generator = run_chat(user, session, body.content, body.repo_ids)

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
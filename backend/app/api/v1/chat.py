import json, time, uuid
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from app.models.schemas import ChatRequest, RetrievedItem, SSEToken, SSEResponseInfo
from app.core.rag.retriever import retrieve
from app.core.llm.factory import get_llm
from app.core.harness.runtime import execute_with_harness
from app.core.harness.config import TIMEOUTS
from app.core.memory.session import add_message
from app.core.memory.context_assembler import assemble_context, check_should_archive
from app.core.memory.archiver import archive_session

router = APIRouter()
SYSTEM = "你是 NovaTech 技术助手，专门帮助程序员解决技术问题。\n- 基于提供的上下文回答"

async def event_stream(question: str, session_id: str):
    start = time.time()
    chunks = []
    try:
        chunks = await execute_with_harness(
            retrieve, question, 10,
            context="chat/retrieval",
            timeout=TIMEOUTS.retrieval_timeout,
            use_retry=True,
            fallback=lambda *a, **kw: [],
        )
    except Exception:
        chunks = []
    retrieval_ms = (time.time() - start) * 1000

    items = [RetrievedItem(id=c.id, content=c.content[:200], source=c.source,
             score_type=c.score_type, score=c.score) for c in chunks]
    yield f"data: {json.dumps({'type': 'retrieval', 'data': [i.model_dump() for i in items]}, ensure_ascii=False)}\n\n"

    add_message(session_id, "user", question)

    # Assemble context from memory
    memory_context = await assemble_context(question, session_id)

    if chunks:
        ctx = "\n\n---\n\n".join(f"[来源: {c.source}]\n{c.content}" for c in chunks)
        msgs = [
            {"role": "system", "content": f"{SYSTEM}\n\n## 参考资料\n\n{ctx}\n\n{memory_context}"},
            {"role": "user", "content": question},
        ]
    else:
        msgs = [
            {"role": "system", "content": f"{SYSTEM}\n\n{memory_context}"},
            {"role": "user", "content": question},
        ]

    full_response = ""
    try:
        llm = get_llm()
        token_count = 0
        async for token in llm.astream(msgs):
            token_count += 1
            full_response += token
            yield f"data: {json.dumps({'type': 'token', 'content': token}, ensure_ascii=False)}\n\n"
    except Exception as e:
        error_msg = f"[LLM错误: {e}]"
        full_response = error_msg
        yield f"data: {json.dumps({'type': 'token', 'content': error_msg}, ensure_ascii=False)}\n\n"
        token_count = 0

    add_message(session_id, "assistant", full_response)

    try:
        from app.core.security.audit import log_audit, AuditAction
        await log_audit(AuditAction.CHAT_MESSAGE, details={"session_id": session_id})
    except Exception:
        pass

    # Auto-archive check
    if check_should_archive(session_id):
        try:
            await archive_session(session_id)
        except Exception:
            pass

    yield f"data: {json.dumps({'type': 'done', 'session_id': session_id, 'retrieval_time_ms': int(retrieval_ms), 'tokens': token_count})}\n\n"


@router.post("/chat/message")
async def chat_message(req: ChatRequest):
    sid = req.session_id or str(uuid.uuid4())
    return StreamingResponse(event_stream(req.message, sid), media_type="text/event-stream")

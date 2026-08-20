import json, time, uuid
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from app.models.schemas import ChatRequest, RetrievedItem
from app.core.rag.retriever import retrieve
from app.core.llm.factory import get_llm
from app.core.harness.runtime import execute_with_harness
from app.core.harness.config import TIMEOUTS
from app.core.memory.session import add_message
from app.core.memory.context_assembler import assemble_context, check_should_archive
from app.core.memory.archiver import archive_session
from app.core.tools import registry as tool_registry, run_tool

router = APIRouter()
SYSTEM = "你是 NovaTech 技术助手，专门帮助程序员解决技术问题。\n- 基于提供的上下文回答"

MAX_TOOL_ROUNDS = 4
SSE_END = chr(10) + chr(10)


def _sse(payload: dict) -> str:
    return "data: " + json.dumps(payload, ensure_ascii=False) + SSE_END


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
    yield _sse({"type": "retrieval", "data": [i.model_dump() for i in items]})

    # 用户消息写入是尽力而为——失败不打断对话
    try:
        await add_message(session_id, "user", question)
    except Exception:
        pass

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
    token_count = 0
    tool_events: list[dict] = []
    tools_spec = tool_registry.to_openai_tools()

    try:
        llm = get_llm()
        for round_index in range(MAX_TOOL_ROUNDS):
            round_content = ""
            pending_calls: list[dict] = []

            async for event in llm.astream_with_tools(msgs, tools_spec):
                if event["type"] == "content":
                    token_count += 1
                    round_content += event["content"]
                    yield _sse({"type": "token", "content": event["content"]})
                elif event["type"] == "tool_calls":
                    pending_calls = event["tool_calls"]

            full_response += round_content

            # LLM 未请求工具 → 对话自然结束
            if not pending_calls:
                break

            # 回填 assistant 的 tool_calls 决策，保持 messages 完整
            msgs.append({
                "role": "assistant",
                "content": round_content or None,
                "tool_calls": [
                    {
                        "id": call.get("id") or f"call_{round_index}_{i}",
                        "type": "function",
                        "function": {"name": call["name"], "arguments": call.get("arguments") or "{}"},
                    }
                    for i, call in enumerate(pending_calls)
                ],
            })

            for i, call in enumerate(pending_calls):
                name = call["name"]
                call_id = call.get("id") or f"call_{round_index}_{i}"
                yield _sse({"type": "tool_call", "id": call_id, "name": name,
                            "arguments": call.get("arguments") or "{}"})

                t0 = time.time()
                result = await run_tool(name, call.get("arguments"))
                duration_ms = int((time.time() - t0) * 1000)

                yield _sse({"type": "tool_result", "id": call_id, "name": name,
                            "duration_ms": duration_ms, "result": result})
                tool_events.append({"name": name, "duration_ms": duration_ms,
                                    "ok": bool(result.get("ok"))})

                msgs.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": json.dumps(result, ensure_ascii=False, default=str),
                })
            # 循环继续 → 下一轮 LLM 能看到工具结果并继续生成
    except Exception as e:
        error_msg = f"[LLM错误: {e}]"
        full_response += error_msg
        yield _sse({"type": "token", "content": error_msg})

    try:
        await add_message(session_id, "assistant", full_response)
    except Exception:
        pass

    try:
        from app.core.security.audit import log_audit, AuditAction
        await log_audit(AuditAction.CHAT_MESSAGE, details={"session_id": session_id})
        if tool_events:
            await log_audit(AuditAction.TOOL_CALL,
                            details={"session_id": session_id, "tools": tool_events})
    except Exception:
        pass

    # Auto-archive check
    if await check_should_archive(session_id):
        try:
            await archive_session(session_id)
        except Exception:
            pass

    yield _sse({"type": "done", "session_id": session_id,
                "retrieval_time_ms": int(retrieval_ms), "tokens": token_count,
                "tools_used": [t["name"] for t in tool_events]})


@router.post("/chat/message")
async def chat_message(req: ChatRequest):
    sid = req.session_id or str(uuid.uuid4())
    return StreamingResponse(event_stream(req.message, sid), media_type="text/event-stream")

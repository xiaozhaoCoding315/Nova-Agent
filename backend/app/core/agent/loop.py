"""Agent loop: RAG context + tool-calling rounds + persistence.

Yields event dicts {"event": str, "data": dict}; the SSE endpoint serializes
them. Persistence lives in a ``finally`` block so that client disconnects
(the stop button) still store whatever was generated.
"""
import asyncio
import json
import time

import structlog

from app.config import settings
from app.core.harness.config import TIMEOUTS
from app.core.llm.factory import get_llm
from app.core.memory import facts as facts_mod
from app.core.memory import session as session_mod
from app.core.memory.context import build_system_prompt
from app.core.rag.retriever import retrieve
from app.core.security.audit import AuditAction, log_audit
from app.core.tools import ToolContext, get_registry

logger = structlog.get_logger()

MAX_TOOL_RESULT_CHARS = 6000


def _sse(event: str, **data) -> dict:
    return {"event": event, "data": data}


def _tool_message(result: dict) -> str:
    payload = {"ok": result["ok"]}
    if result["ok"]:
        payload["output"] = result.get("output")
    else:
        payload["error"] = result.get("error", "unknown error")
    payload["ms"] = result.get("ms", 0)
    return json.dumps(payload, ensure_ascii=False, default=str)[:MAX_TOOL_RESULT_CHARS]


def _result_preview(result: dict, limit: int = 400) -> str:
    text = json.dumps(
        result.get("output") if result["ok"] else {"error": result.get("error")},
        ensure_ascii=False, default=str,
    )
    return text[:limit]


async def _record_usage(user: dict, session_id: str, usage: dict, tool_count: int) -> None:
    from app.db import execute
    try:
        await execute(
            "INSERT INTO usage_log (user_id, session_id, model, prompt_tokens, completion_tokens, tool_calls) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (
                user["id"], session_id, (usage.get("model") or "unknown")[:64],
                int(usage.get("prompt_tokens") or 0),
                int(usage.get("completion_tokens") or 0),
                tool_count,
            ),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("usage_record_failed", error=str(exc))


async def run_chat(user: dict, session: dict, user_message: str, repo_ids: list[str]):
    started = time.perf_counter()
    registry = get_registry()
    tools_used: list[str] = []
    content_parts: list[str] = []
    usage_total = {"prompt_tokens": 0, "completion_tokens": 0, "model": ""}
    rounds = 0

    yield _sse("meta", session_id=session["id"], title=session["title"])

    # 1) retrieval
    hits: list = []
    retrieval_started = time.perf_counter()
    try:
        hits = await asyncio.wait_for(
            retrieve(user_message, top_k=8, repo_ids=repo_ids or None),
            timeout=TIMEOUTS.retrieval_timeout + 5,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("retrieval_failed", error=str(exc))
    yield _sse(
        "retrieval",
        took_ms=int((time.perf_counter() - retrieval_started) * 1000),
        hits=[
            {
                "path": h.path, "line_start": h.line_start, "line_end": h.line_end,
                "score": round(h.score, 3), "source": h.score_type, "kind": h.kind,
                "snippet": h.content[:300],
            }
            for h in hits[:5]
        ],
    )

    # 2) context assembly
    fact_list: list[str] = []
    try:
        fact_list = await facts_mod.get_relevant_facts(user["id"])
    except Exception as exc:  # noqa: BLE001
        logger.warning("facts_load_failed", error=str(exc))
    history = await session_mod.recent_messages(session["id"])
    messages: list[dict] = [
        {"role": "system", "content": build_system_prompt(hits, fact_list, repo_selected=bool(repo_ids))},
        *history,
    ]

    ctx = ToolContext(user=user, repo_ids=repo_ids or [])
    specs = registry.specs()
    holder = {"message_id": 0}

    async def _persist_turn() -> int:
        final_text = "".join(content_parts).strip()
        message_id = await session_mod.add_message(
            session["id"], "assistant", final_text,
            tool_json={"tools_used": tools_used} if tools_used else None,
            prompt_tokens=usage_total["prompt_tokens"],
            completion_tokens=usage_total["completion_tokens"],
        )
        await _record_usage(user, session["id"], usage_total, len(tools_used))
        await log_audit(
            AuditAction.CHAT_MESSAGE,
            user_id=str(user["id"]),
            details={
                "session_id": session["id"],
                "tools": tools_used,
                "elapsed_ms": int((time.perf_counter() - started) * 1000),
                "rounds": rounds,
            },
        )
        if final_text:
            asyncio.create_task(
                facts_mod.extract_facts_from_turn(user["id"], user_message, final_text)
            )
        logger.info("chat_done", session=session["id"], tools=tools_used, rounds=rounds)
        return message_id

    try:
        # 3) tool-calling rounds
        for round_no in range(1, settings.max_rounds + 1):
            rounds = round_no
            round_text: list[str] = []
            tool_calls: list[dict] = []
            usage: dict | None = None

            try:
                async with asyncio.timeout(settings.llm_timeout):
                    async for event in get_llm().astream_with_tools(messages, specs):
                        etype = event.get("type")
                        if etype == "content":
                            round_text.append(event["content"])
                            content_parts.append(event["content"])
                            yield _sse("token", text=event["content"])
                        elif etype == "tool_calls":
                            tool_calls = event["tool_calls"]
                        elif etype == "usage":
                            usage = event["usage"]
            except TimeoutError:
                yield _sse("error", code="llm_timeout",
                           message=f"模型响应超时（{settings.llm_timeout}s），请重试或换个问法")
                break
            except Exception as exc:  # noqa: BLE001
                logger.warning("llm_call_failed", error=str(exc))
                yield _sse("error", code="llm_error", message=f"模型调用失败：{exc}")
                break

            if usage:
                usage_total["prompt_tokens"] += int(usage.get("prompt_tokens") or 0)
                usage_total["completion_tokens"] += int(usage.get("completion_tokens") or 0)
                usage_total["model"] = usage.get("model") or usage_total["model"]

            text = "".join(round_text)

            if not tool_calls:
                break

            messages.append({
                "role": "assistant",
                "content": text,
                "tool_calls": [
                    {"id": tc["id"], "type": "function",
                     "function": {"name": tc["name"], "arguments": tc["arguments"]}}
                    for tc in tool_calls
                ],
            })

            for tc in tool_calls:
                name = tc.get("name", "")
                try:
                    args = json.loads(tc.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                yield _sse("tool_call", id=tc.get("id", ""), name=name, args=args, round=round_no)
                result = await registry.execute(name, args, ctx)
                tools_used.append(name)
                yield _sse(
                    "tool_result", id=tc.get("id", ""), name=name, ok=result["ok"],
                    ms=result["ms"], preview=_result_preview(result),
                )
                messages.append({
                    "role": "tool", "tool_call_id": tc.get("id", ""),
                    "name": name, "content": _tool_message(result),
                })

        yield _sse(
            "usage",
            model=usage_total["model"],
            prompt_tokens=usage_total["prompt_tokens"],
            completion_tokens=usage_total["completion_tokens"],
        )
    except BaseException:
        # Client pressed stop / disconnected: the request task is being
        # cancelled, so awaiting persistence here would be interrupted.
        # Persist in a background task instead and re-raise.
        if "".join(content_parts).strip() or tools_used:
            asyncio.create_task(_persist_turn())
        raise

    # 4) persistence on the normal path (message_id is needed for the done event)
    if "".join(content_parts).strip() or tools_used:
        try:
            holder["message_id"] = await _persist_turn()
        except Exception as exc:  # noqa: BLE001
            logger.error("chat_persist_failed", error=str(exc))

    yield _sse(
        "done",
        message_id=holder["message_id"],
        elapsed_ms=int((time.perf_counter() - started) * 1000),
        tools_used=tools_used,
        rounds=rounds,
    )
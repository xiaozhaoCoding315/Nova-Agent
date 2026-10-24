"""Agent loop: RAG context + tool-calling rounds + persistence.

Yields event dicts {"event": str, "data": dict}; the SSE endpoint serializes
them. Persistence lives in a ``finally`` block so that client disconnects
(the stop button) still store whatever was generated.
"""
import asyncio
import json
import time
import uuid

import structlog
from fastapi import HTTPException

from app.config import settings
from app.core.agent.report import build_turn_report
from app.core.agent.rules import load_repo_rules
from app.core.harness.config import TIMEOUTS
from app.core.llm.factory import get_llm
from app.core.llm.usage import record_usage
from app.core.memory import facts as facts_mod
from app.core.memory import session as session_mod
from app.core.memory.context import build_system_prompt
from app.core.rag.retriever import retrieve
from app.core.security.audit import AuditAction, log_audit
from app.core.security.limits import ensure_token_budget
from app.core.security.redaction import redact_obj, redact_text
from app.core.trace import record as trace_record
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
    await record_usage(user["id"], session_id, usage, tool_calls=tool_count, source="chat")


async def run_chat(
    user: dict, session: dict, user_message: str, repo_ids: list[str],
    turn_id: str | None = None, attachments: list[dict] | None = None,
):
    started = time.perf_counter()
    turn_id = turn_id or str(uuid.uuid4())
    await trace_record(session["id"], turn_id, "turn_start", {
        "user": user_message[:2000], "repos": repo_ids,
        "permission": session.get("permission_mode", "ask"),
    })
    registry = get_registry()
    tools_used: list[str] = []
    tool_events: list[dict] = []
    edits: list[dict] = []
    content_parts: list[str] = []
    usage_total = {"prompt_tokens": 0, "completion_tokens": 0, "model": ""}
    rounds = 0
    sandbox_runs_ok = 0
    errors: list[str] = []

    yield _sse(
        "meta",
        session_id=session["id"],
        title=session["title"],
        repo_ids=session.get("repo_ids", repo_ids),
        model=session.get("model"),
        turn_id=turn_id,
    )

    # 1) retrieval
    hits: list = []
    retrieval_started = time.perf_counter()
    try:
        hits = await asyncio.wait_for(
            retrieve(user_message, top_k=8, repo_ids=repo_ids),
            timeout=TIMEOUTS.retrieval_timeout + 5,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("retrieval_failed", error=str(exc))
    retrieval_ms = int((time.perf_counter() - retrieval_started) * 1000)
    await trace_record(session["id"], turn_id, "retrieval", {
        "took_ms": retrieval_ms,
        "hits": [{"path": h.path, "line": h.line_start, "source": h.score_type} for h in hits[:8]],
    })
    yield _sse(
        "retrieval",
        took_ms=retrieval_ms,
        hits=[
            {
                "path": h.path, "line_start": h.line_start, "line_end": h.line_end,
                "score": round(h.score, 3), "source": h.score_type, "kind": h.kind,
                "snippet": redact_text(h.content[:300]),
            }
            for h in hits[:5]
        ],
    )

    # 2) context assembly
    fact_list: list[str] = []
    try:
        fact_list = await facts_mod.get_relevant_facts(user["id"], user_message)
    except Exception as exc:  # noqa: BLE001
        logger.warning("facts_load_failed", error=str(exc))
    history = await session_mod.recent_messages(
        session["id"], after_id=int(session.get("summary_upto_id") or 0)
    )
    repo_meta: list[dict] = []
    for rid in repo_ids or []:
        try:
            from app.core.indexing.pipeline import get_repo
            repo = await get_repo(rid, user["id"])
            if repo:
                repo_meta.append({
                    "id": repo["id"], "name": repo["name"],
                    "root_path": repo.get("root_path"), "rules": repo.get("rules") or "",
                })
        except Exception:  # noqa: BLE001
            continue
    repo_rules = load_repo_rules(repo_meta)
    system_content = build_system_prompt(
        hits, fact_list, repo_selected=bool(repo_ids),
        repos=repo_meta, rules=repo_rules,
        summary=session.get("summary") or "",
    )
    if attachments:
        lines = [
            f"- {item['filename']}（id={item['id']}，{item['mime']}，{item['size']} bytes）"
            for item in attachments[:5]
        ]
        system_content += (
            "\n\n本轮用户上传了附件：\n" + "\n".join(lines)
            + "\n如需读取附件内容，请调用 read_uploaded_file 工具，不要臆测内容。"
        )
    messages: list[dict] = [
        {"role": "system", "content": system_content},
        *history,
    ]

    ctx = ToolContext(
        user=user,
        repo_ids=repo_ids or [],
        repo_roots={r["id"]: r["root_path"] for r in repo_meta if r.get("root_path")},
        session_id=session["id"],
        permission_mode=session.get("permission_mode", "ask"),
        file_ids=[item["id"] for item in (attachments or [])][:5],
    )
    specs = registry.specs()
    holder: dict = {"message_id": 0, "evidence": None, "report": None}

    async def _build_evidence() -> dict:
        if holder["evidence"] is not None:
            return holder["evidence"]
        try:
            from app.core.agent.evidence import verify_citations
            holder["evidence"] = await verify_citations(
                "".join(content_parts).strip(), repo_ids or [], executed=sandbox_runs_ok > 0
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("evidence_verify_failed", error=str(exc))
            holder["evidence"] = {"executed": sandbox_runs_ok > 0, "citations": [],
                                  "verified": 0, "missing": 0, "out_of_range": 0, "skipped": 0}
        return holder["evidence"]

    async def _build_report() -> dict:
        if holder["report"] is not None:
            return holder["report"]
        holder["report"] = build_turn_report(
            user_message=user_message,
            repos=repo_meta,
            permission_mode=session.get("permission_mode", "ask"),
            tools=tool_events,
            edits=edits,
            evidence=await _build_evidence(),
            usage=usage_total,
            rounds=rounds,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            final_text="".join(content_parts).strip(),
            errors=errors,
        )
        return holder["report"]

    async def _persist_turn() -> int:
        final_text = "".join(content_parts).strip()
        tool_json: dict | None = None
        if tools_used or final_text:
            tool_json = {"tools_used": tools_used}
            if edits:
                tool_json["edits"] = edits
            if final_text:
                tool_json["evidence"] = await _build_evidence()
            tool_json["report"] = await _build_report()
        message_id = await session_mod.add_message(
            session["id"], "assistant", final_text,
            tool_json=tool_json,
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
        try:
            from app.core.jobs.service import enqueue_session_summary, is_running
            from app.core.memory.summary import SUMMARY_BATCH

            if is_running():
                upto_id = int(session.get("summary_upto_id") or 0)
                pending = await session_mod.count_messages_since(session["id"], upto_id)
                if pending >= SUMMARY_BATCH:
                    await enqueue_session_summary(session["id"], user["id"])
        except Exception as exc:  # noqa: BLE001
            logger.debug("summary_enqueue_failed", error=str(exc))
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
                await ensure_token_budget(
                    user,
                    extra_tokens=usage_total["prompt_tokens"] + usage_total["completion_tokens"],
                )
            except HTTPException as exc:
                errors.append(f"配额限制：{exc.detail}")
                await trace_record(session["id"], turn_id, "error", {"code": "quota_exceeded"})
                yield _sse("error", code="quota_exceeded", message=str(exc.detail))
                break

            try:
                llm = await get_llm(user["id"], model=session.get("model"))
                async with asyncio.timeout(settings.llm_timeout):
                    async for event in llm.astream_with_tools(messages, specs):
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
                errors.append(f"模型响应超时（{settings.llm_timeout}s）")
                await trace_record(session["id"], turn_id, "error", {"code": "llm_timeout"})
                yield _sse("error", code="llm_timeout",
                           message=f"模型响应超时（{settings.llm_timeout}s），请重试或换个问法")
                break
            except Exception as exc:  # noqa: BLE001
                logger.warning("llm_call_failed", error=str(exc))
                errors.append(f"模型调用失败：{str(exc)[:300]}")
                await trace_record(session["id"], turn_id, "error", {"code": "llm_error", "message": str(exc)[:500]})
                yield _sse("error", code="llm_error", message=f"模型调用失败：{exc}")
                break

            if usage:
                usage_total["prompt_tokens"] += int(usage.get("prompt_tokens") or 0)
                usage_total["completion_tokens"] += int(usage.get("completion_tokens") or 0)
                usage_total["model"] = usage.get("model") or usage_total["model"]

            text = "".join(round_text)
            await trace_record(session["id"], turn_id, "llm_round", {
                "round": round_no, "chars": len(text),
                "usage": usage or {}, "tool_calls": len(tool_calls),
            })

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
                yield _sse("tool_call", id=tc.get("id", ""), name=name, args=redact_obj(args), round=round_no)
                await trace_record(session["id"], turn_id, "tool_call", {
                    "name": name, "args": _preview_for_trace(args),
                })
                result = await registry.execute(name, args, ctx)
                tools_used.append(name)
                if name == "run_code" and result["ok"] and (result.get("output") or {}).get("exit_code") == 0:
                    sandbox_runs_ok += 1
                output = result.get("output") if result["ok"] else None
                tool_events.append({
                    "name": name,
                    "ok": bool(result["ok"]),
                    "ms": int(result.get("ms") or 0),
                    "command": redact_text(output.get("command")) if isinstance(output, dict) else None,
                    "exit_code": output.get("exit_code") if isinstance(output, dict) else None,
                    "timed_out": bool(output.get("timed_out")) if isinstance(output, dict) else False,
                    "args": redact_obj(_args_summary(args)),
                    "error": redact_text(result.get("error")) if not result["ok"] else None,
                })
                if isinstance(output, dict) and output.get("edit_id"):
                    edit_entry = {
                        "id": output["edit_id"],
                        "files": output.get("files", []),
                        "staged": bool(output.get("staged")),
                        "status": output.get("status", ""),
                    }
                    edits.append(edit_entry)
                    await trace_record(session["id"], turn_id, "edit_proposal", edit_entry)
                    yield _sse(
                        "edit_proposal",
                        id=edit_entry["id"],
                        files=edit_entry["files"],
                        staged=edit_entry["staged"],
                        status=edit_entry["status"],
                        diff=output.get("diff_preview", "")[:2000],
                    )
                await trace_record(session["id"], turn_id, "tool_result", {
                    "name": name, "ok": result["ok"], "ms": result["ms"],
                    "preview": _result_preview(result)[:800],
                })
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
        if "".join(content_parts).strip():
            evidence = await _build_evidence()
            yield _sse("evidence", **evidence)
        report = await _build_report() if (content_parts or tools_used) else None
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

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    await trace_record(session["id"], turn_id, "done", {
        "final_text": "".join(content_parts).strip()[:3000],
        "tools_used": tools_used, "rounds": rounds, "elapsed_ms": elapsed_ms,
        "message_id": holder["message_id"],
    })
    yield _sse(
        "done",
        message_id=holder["message_id"],
        elapsed_ms=elapsed_ms,
        tools_used=tools_used,
        rounds=rounds,
        turn_id=turn_id,
        report=report,
    )

def _args_summary(args: dict) -> dict:
    summary: dict = {}
    for key in ("command", "path", "query", "repo_id", "note", "url"):
        if args.get(key):
            summary[key] = str(args[key])[:300]
    if isinstance(args.get("files"), dict):
        summary["files"] = list(args["files"])[:8]
    return summary


def _preview_for_trace(args: dict, limit: int = 500) -> str:
    try:
        return json.dumps(args, ensure_ascii=False, default=str)[:limit]
    except (TypeError, ValueError):
        return str(args)[:limit]

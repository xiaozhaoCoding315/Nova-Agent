"""Agent loop: RAG context + tool-calling rounds + persistence.

Yields event dicts {"event": str, "data": dict}; the SSE endpoint serializes
them. Persistence lives in a ``finally`` block so that client disconnects
(the stop button) still store whatever was generated.
"""
import asyncio
import itertools
import json
import time
import uuid

import structlog
from fastapi import HTTPException

from app.config import settings
from app.core.agent.context_meter import estimate_messages, estimate_tokens
from app.core.agent.report import build_turn_report
from app.core.agent.rules import load_repo_rules
from app.core.harness.config import TIMEOUTS
from app.core.llm.factory import get_llm, resolve_context_window
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
    active_lesson_ids: list[str] = []

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
            retrieve(user_message, top_k=8, repo_ids=repo_ids, user_id=user["id"]),
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
        session["id"], after_id=int(session.get("summary_upto_id") or 0),
        user_id=user["id"],
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
    prompt_sections: dict[str, str] = {}
    system_content = build_system_prompt(
        hits, fact_list, repo_selected=bool(repo_ids),
        repos=repo_meta, rules=repo_rules,
        summary=session.get("summary") or "",
        sections=prompt_sections,
    )
    attachment_block = ""
    if attachments:
        lines = [
            f"- {item['filename']}（id={item['id']}，{item['mime']}，{item['size']} bytes）"
            for item in attachments[:5]
        ]
        attachment_block = (
            "\n\n本轮用户上传了附件：\n" + "\n".join(lines)
            + "\n如需读取附件内容，请调用 read_uploaded_file 工具，不要臆测内容。"
        )
        system_content += attachment_block
    try:
        from app.core.skills import build_skill_prompt
        skill_prompt = build_skill_prompt(user_message)
        if skill_prompt:
            prompt_sections["skills"] = skill_prompt
            system_content += f"\n\n{skill_prompt}"
    except Exception as exc:  # noqa: BLE001
        logger.warning("skills_inject_failed", error=str(exc))
    try:
        from app.core.reflection import lessons_for_context
        lesson_list = await lessons_for_context(user["id"], repo_ids or [])
        if lesson_list:
            active_lesson_ids = [item["id"] for item in lesson_list]
            lines = [f"- {item['content']}" for item in lesson_list]
            lesson_block = (
                "\n\n## 已吸取的教训（来自过往失败与返工，遵循可避免重复犯错）\n"
                + "\n".join(lines)
            )
            prompt_sections["lessons"] = lesson_block
            system_content += lesson_block
    except Exception as exc:  # noqa: BLE001
        logger.warning("lessons_inject_failed", error=str(exc))
    messages: list[dict] = [
        {"role": "system", "content": system_content},
        *history,
    ]

    # 上下文计量：分段估算本次提示的构成，供前端展示「用了多少、用在哪里」。
    context_window = resolve_context_window(user["id"])
    section_labels = {
        "identity": "系统提示", "summary": "会话摘要", "repos": "仓库说明",
        "rules": "项目规则", "retrieval": "代码检索", "facts": "长期记忆",
        "skills": "技能注入", "lessons": "经验教训", "attachments": "附件",
    }
    section_tokens = {
        section_labels.get(key, key): estimate_tokens(text)
        for key, text in prompt_sections.items()
    }
    section_tokens["附件"] = estimate_tokens(attachment_block)
    section_tokens = {key: value for key, value in section_tokens.items() if value > 0}
    history_tokens = estimate_messages(history) + estimate_tokens(user_message) + 8
    section_tokens["历史与提问"] = history_tokens
    context_total = sum(section_tokens.values())
    context_info = {
        "window": context_window,
        "sections": section_tokens,
        "total": context_total,
        "estimate": True,
    }
    yield _sse("context", **context_info)

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
            # Per-call details so historical messages can render the same
            # collapsible tool cards seen while streaming.
            if tool_events:
                tool_json["tool_events"] = tool_events[-40:]
            if edits:
                tool_json["edits"] = edits
            if final_text:
                tool_json["evidence"] = await _build_evidence()
            tool_json["report"] = await _build_report()
            # 历史消息回看时也能展示本轮上下文构成
            if usage_total["prompt_tokens"]:
                context_info["actual_prompt_tokens"] = usage_total["prompt_tokens"]
            tool_json["context"] = context_info
        message_id = await session_mod.add_message(
            session["id"], "assistant", final_text,
            tool_json=tool_json,
            prompt_tokens=usage_total["prompt_tokens"],
            completion_tokens=usage_total["completion_tokens"],
        )
        await _record_usage(user, session["id"], usage_total, len(tools_used))
        if active_lesson_ids:
            try:
                from app.core.reflection import record_outcome
                await record_outcome(active_lesson_ids, ok=not errors)
            except Exception as exc:  # noqa: BLE001
                logger.debug("lesson_outcome_failed", error=str(exc))
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
                pending = await session_mod.count_messages_since(
                    session["id"], upto_id, user_id=user["id"]
                )
                if pending >= SUMMARY_BATCH:
                    await enqueue_session_summary(session["id"], user["id"])
        except Exception as exc:  # noqa: BLE001
            logger.debug("summary_enqueue_failed", error=str(exc))
        logger.info("chat_done", session=session["id"], tools=tools_used, rounds=rounds)
        return message_id

    CONTINUE_INSTRUCTION = (
        "系统提示：你已连续调用多轮工具。请从中断处继续完成任务；"
        "若任务已完成，请直接给出最终答复与总结，不要再调用工具。"
    )
    try:
        # 3) tool-calling rounds — 长任务模式：段触顶注入继续指令而不是终止，
        #    瞬时失败自动重试（对齐主流 Agent 的 driver 续跑模式）
        rounds = 0
        continuations_left = max(int(settings.max_continuations), 0)
        turn_deadline = time.monotonic() + max(int(settings.turn_timeout), 60)
        for round_no in itertools.count(1):
            if time.monotonic() > turn_deadline:
                errors.append("任务时长达到上限（自动暂停）")
                yield _sse("notice", kind="incomplete",
                           message="任务执行时间较长，已自动暂停。点击「继续任务」接着做。")
                break
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

            llm_failed: str | None = None
            llm_error_detail = ""
            for attempt in range(max(int(settings.llm_round_retries), 0) + 1):
                llm_failed = None
                llm_error_detail = ""
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
                    break
                except TimeoutError:
                    llm_failed = "timeout"
                except Exception as exc:  # noqa: BLE001
                    llm_failed = "error"
                    llm_error_detail = str(exc)
                if round_text or tool_calls or attempt >= max(int(settings.llm_round_retries), 0):
                    break
                yield _sse("notice", kind="retry",
                           message=f"模型连接抖动，自动重试（{attempt + 2}/{max(int(settings.llm_round_retries), 0) + 1}）…")

            if llm_failed:
                had_output = bool(round_text or tool_calls)
                if continuations_left > 0:
                    # 中断续跑：已流出的部分作为 assistant 消息入库，让模型接着写
                    continuations_left -= 1
                    if had_output:
                        messages.append({"role": "assistant", "content": "".join(round_text)})
                    messages.append({"role": "user", "content": CONTINUE_INSTRUCTION})
                    reason = "超时" if llm_failed == "timeout" else "连接错误"
                    errors.append(f"模型调用{reason}，已自动从中断处继续")
                    await trace_record(session["id"], turn_id, "llm_continued", {"reason": reason})
                    yield _sse("notice", kind="continued", message=f"模型调用{reason}，已自动从中断处继续…")
                    continue
                if llm_failed == "timeout":
                    errors.append(f"模型响应超时（{settings.llm_timeout}s）")
                    await trace_record(session["id"], turn_id, "error", {"code": "llm_timeout"})
                    yield _sse("error", code="llm_timeout",
                               message="模型响应超时。点击「继续任务」可从中断处接着做。")
                else:
                    logger.warning("llm_call_failed", error=llm_error_detail[:300])
                    errors.append(f"模型调用失败：{llm_error_detail[:300]}")
                    await trace_record(session["id"], turn_id, "error",
                                       {"code": "llm_error", "message": llm_error_detail[:500]})
                    yield _sse("error", code="llm_error", message=f"模型调用失败：{llm_error_detail}")
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
                    "round": round_no,
                    "command": redact_text(output.get("command")) if isinstance(output, dict) else None,
                    "exit_code": output.get("exit_code") if isinstance(output, dict) else None,
                    "timed_out": bool(output.get("timed_out")) if isinstance(output, dict) else False,
                    "args": redact_obj(_args_summary(args)),
                    "error": redact_text(result.get("error")) if not result["ok"] else None,
                    "preview": _result_preview(result),
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

            # 段触顶：注入继续指令接着跑（主流 driver 续跑模式）
            if round_no >= settings.max_rounds:
                if continuations_left > 0:
                    continuations_left -= 1
                    messages.append({"role": "user", "content": CONTINUE_INSTRUCTION})
                    await trace_record(session["id"], turn_id, "rounds_continued", {"round": round_no})
                    yield _sse("notice", kind="continued",
                               message="任务较大，已自动开启下一段继续执行…")
                else:
                    yield _sse("notice", kind="incomplete",
                               message="任务轮次较多，本轮先到这里。点击「继续任务」接着做。")
                    break

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

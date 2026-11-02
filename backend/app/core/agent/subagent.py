"""Read-only sub-agent runner.

A sub-agent gets its own message list and a fixed read-only tool set.  It
never writes files, runs commands, uses the network, or spawns more agents.
The parent chat loop calls this through the ``spawn_agents`` tool and receives
one JSON-serializable summary per task.
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING, Awaitable, Callable

import structlog
from fastapi import HTTPException

from app.config import settings
from app.core.agent.context_governor import compact_messages
from app.core.agent.evidence import extract_citations, verify_citations
from app.core.agent.tool_output import serialize_tool_result
from app.core.llm.factory import (
    LLMNotConfiguredError,
    get_llm,
    resolve_context_window,
)
from app.core.llm.usage import record_usage
from app.core.security.limits import ensure_token_budget
from app.core.security.redaction import redact_text
from app.core.trace import record as trace_record

if TYPE_CHECKING:
    from app.core.tools.base import ToolRegistry


logger = structlog.get_logger()

SUBAGENT_TOOL_ALLOWLIST = frozenset({
    "read_file", "list_files", "grep", "glob", "search_code",
    "impact_analysis", "diagnose_error", "json_tool", "sql_tool",
})

SUBAGENT_IDENTITY = """你是 Nova 的只读子代理，只负责被指派的一项调研/审查任务。

规则：
1. 只读：不得修改任何文件、不得执行命令、不得联网，也不要声称做过这些事。
2. 引用代码必须给出 文件路径:行号；不确定的结论要明确标注不确定。
3. 先自己检索和读文件，不要假设上级代理已经看过代码。
4. 最终用中文给出简洁结论，结构如下：
## 结论
一两句话回答任务。
## 关键发现
- [path/to/file.py:42] 具体发现
## 建议
可选的后续动作。
5. 不要输出与任务无关的完整文件内容。"""


class _StopSubagent(Exception):
    """Internal control flow: finish early after a terminal error."""


def _parse_arguments(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(raw or "{}")
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


def _extract_findings(summary: str, limit: int = 12) -> list[dict]:
    findings: list[dict] = []
    for line in summary.splitlines():
        stripped = line.strip()
        if not stripped.startswith(("-", "*")):
            continue
        citations = extract_citations(stripped)
        if not citations:
            continue
        first = citations[0]
        detail = stripped.lstrip("-* ").strip()
        findings.append({
            "title": detail[:80] or "发现",
            "detail": detail[:300],
            "file": first["path"],
            "line": first["line"],
        })
        if len(findings) >= limit:
            break
    return findings


async def _stream_round(
    llm, messages: list[dict], specs: list[dict],
) -> tuple[str, list[dict], dict | None]:
    """One tool-enabled LLM round with the same transient retry as the parent."""
    last_error: Exception | None = None
    attempts = max(int(settings.llm_round_retries), 0) + 1
    for _ in range(attempts):
        content: list[str] = []
        tool_calls: list[dict] = []
        usage: dict | None = None
        try:
            async with asyncio.timeout(settings.llm_timeout):
                async for event in llm.astream_with_tools(messages, specs):
                    etype = event.get("type")
                    if etype == "content":
                        content.append(event.get("content") or "")
                    elif etype == "tool_calls":
                        tool_calls = event.get("tool_calls") or []
                    elif etype == "usage":
                        usage = event.get("usage")
            return "".join(content), tool_calls, usage
        except TimeoutError as exc:
            last_error = exc
        except Exception as exc:  # noqa: BLE001
            last_error = exc
        if content or tool_calls:
            return "".join(content), tool_calls, usage
    raise last_error or RuntimeError("模型调用失败")


async def _final_summary(llm, messages: list[dict]) -> str:
    """Ask for a final answer without tools; best-effort on provider errors."""
    parts: list[str] = []
    try:
        async with asyncio.timeout(settings.llm_timeout):
            async for token in llm.astream(messages):
                if token:
                    parts.append(str(token))
    except Exception as exc:  # noqa: BLE001
        logger.warning("subagent_final_summary_failed", error=str(exc))
    return "".join(parts)


async def run_subagent(
    *,
    user: dict,
    session_id: str,
    turn_id: str,
    task_id: str,
    title: str,
    prompt: str,
    repo_ids: list[str],
    repos: list[dict] | None = None,
    repo_roots: dict[str, str] | None = None,
    emit: Callable[[dict], Awaitable[None]] | None = None,
    model: str | None = None,
    overrides: dict | None = None,
    max_rounds: int | None = None,
    timeout: float | None = None,
    registry: ToolRegistry | None = None,
) -> dict:
    started = time.perf_counter()
    max_rounds = max(
        1, int(max_rounds if max_rounds is not None else settings.subagent_max_rounds)
    )
    timeout = max(1.0, float(timeout if timeout is not None else settings.subagent_timeout))
    rounds = 0
    tools_used: list[str] = []
    usage_total = {"prompt_tokens": 0, "completion_tokens": 0, "model": ""}
    summary_parts: list[str] = []
    last_text = ""
    status = "ok"
    error: str | None = None

    async def _emit(payload: dict) -> None:
        if emit is None:
            return
        try:
            await emit(payload)
        except Exception:  # noqa: BLE001 — progress must not break the task
            logger.debug("subagent_emit_failed", task_id=task_id)

    if registry is None:
        from app.core.tools import get_registry
        registry = get_registry()

    # 延迟导入：tools 包会导入本模块，模块级导入会形成循环。
    from app.core.tools.base import ToolContext

    specs = [
        spec for spec in registry.specs(
            permission_mode="readonly", sandbox_available=False, local_available=False,
        )
        if spec.get("function", {}).get("name") in SUBAGENT_TOOL_ALLOWLIST
    ]

    system_parts = [SUBAGENT_IDENTITY]
    if repos:
        lines = ["\n## 可访问仓库（工具参数 repo_id 可使用下面的 id）"]
        for repo in repos:
            lines.append(
                f"- {repo.get('name') or repo.get('id')}（repo_id: {repo.get('id')}）"
            )
        system_parts.append("\n".join(lines))
        rule_blocks = [
            f"### {repo.get('name') or repo.get('id')}\n{redact_text(str(repo.get('rules')))}"
            for repo in repos
            if str(repo.get("rules") or "").strip()
        ]
        if rule_blocks:
            system_parts.append(
                "\n## 仓库项目约定（必须遵守）\n" + "\n".join(rule_blocks)
            )

    messages: list[dict] = [
        {"role": "system", "content": "\n".join(system_parts)},
        {"role": "user", "content": prompt},
    ]
    ctx = ToolContext(
        user=user,
        repo_ids=list(repo_ids),
        repo_roots=dict(repo_roots or {}),
        session_id=session_id,
        permission_mode="readonly",
    )

    await _emit({"phase": "start", "id": task_id, "title": title})
    await trace_record(session_id, turn_id, "subagent_start", {
        "id": task_id, "title": title, "repo_ids": list(repo_ids),
    })

    try:
        async with asyncio.timeout(timeout):
            try:
                llm = await get_llm(user["id"], model=model, overrides=overrides)
            except LLMNotConfiguredError as exc:
                status, error = "failed", str(exc)
                raise _StopSubagent() from exc
            except Exception as exc:  # noqa: BLE001
                status, error = "failed", redact_text(str(exc))[:300]
                raise _StopSubagent() from exc

            completed = False
            for round_no in range(1, max_rounds + 1):
                rounds = round_no
                await _emit({"phase": "round", "id": task_id, "round": round_no})
                try:
                    await ensure_token_budget(
                        user,
                        extra_tokens=(
                            usage_total["prompt_tokens"]
                            + usage_total["completion_tokens"]
                        ),
                    )
                except HTTPException as exc:
                    status, error = "failed", redact_text(str(exc.detail))[:300]
                    raise _StopSubagent() from exc

                window = resolve_context_window(user["id"], llm, overrides)
                compact_messages(messages, window, keep_recent=6)

                text, tool_calls, usage = await _stream_round(llm, messages, specs)
                if text:
                    last_text = text
                if usage:
                    usage_total["prompt_tokens"] += int(usage.get("prompt_tokens") or 0)
                    usage_total["completion_tokens"] += int(
                        usage.get("completion_tokens") or 0
                    )
                    usage_total["model"] = str(
                        usage.get("model") or usage_total["model"]
                    )

                if not tool_calls:
                    summary_parts.append(text)
                    completed = True
                    break

                messages.append({
                    "role": "assistant",
                    "content": text,
                    "tool_calls": [
                        {
                            "id": call.get("id") or "",
                            "type": "function",
                            "function": {
                                "name": call.get("name") or "",
                                "arguments": call.get("arguments") or "{}",
                            },
                        }
                        for call in tool_calls
                    ],
                })
                for call in tool_calls:
                    name = str(call.get("name") or "")
                    args = _parse_arguments(call.get("arguments"))
                    if name not in SUBAGENT_TOOL_ALLOWLIST:
                        result = {
                            "ok": False,
                            "error": f"子代理不允许使用工具：{name}",
                            "ms": 0, "business": True, "error_class": "policy",
                        }
                    else:
                        result = await registry.execute(name, args, ctx)
                    tools_used.append(name)
                    await _emit({
                        "phase": "tool", "id": task_id, "name": name,
                        "ok": bool(result.get("ok")),
                    })
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call.get("id") or "",
                        "name": name,
                        "content": serialize_tool_result(name, result),
                    })

            if not completed and status == "ok":
                status = "partial"
                messages.append({
                    "role": "user",
                    "content": (
                        "已达到工具调用上限。请现在基于已有信息给出最终总结，"
                        "不要再调用工具。"
                    ),
                })
                final = await _final_summary(llm, messages)
                if final.strip():
                    summary_parts.append(final)
    except TimeoutError:
        status = "timeout"
        error = f"子代理超过 {int(timeout)} 秒未完成"
    except _StopSubagent:
        pass
    except Exception as exc:  # noqa: BLE001
        status = "failed"
        error = redact_text(str(exc))[:300]
        logger.warning("subagent_failed", task_id=task_id, error=str(exc))

    summary_full = (
        "\n\n".join(part for part in summary_parts if part.strip()).strip()
        or last_text.strip()
    )
    summary = summary_full[:max(int(settings.subagent_summary_chars), 200)]
    if status == "ok" and not summary:
        status = "failed"
        error = error or "子代理没有返回总结"
    if status == "partial" and not summary:
        summary = "子代理达到轮次/时长上限，未形成可读总结。"

    citations = {
        "citations": [], "executed": False, "verified": 0,
        "missing": 0, "out_of_range": 0, "skipped": 0,
    }
    if summary_full:
        try:
            citations = await verify_citations(summary_full, list(repo_ids), False)
        except Exception as exc:  # noqa: BLE001
            logger.warning("subagent_citations_failed", task_id=task_id, error=str(exc))

    try:
        await record_usage(
            user["id"], session_id,
            {
                "prompt_tokens": usage_total["prompt_tokens"],
                "completion_tokens": usage_total["completion_tokens"],
                "model": usage_total["model"],
            },
            tool_calls=len(tools_used), source="subagent",
        )
    except Exception:  # noqa: BLE001 — accounting is best-effort
        pass

    result = {
        "id": task_id,
        "title": title,
        "status": status,
        "summary": summary,
        "findings": _extract_findings(summary_full or summary),
        "files": list(dict.fromkeys(
            item["path"] for item in extract_citations(summary_full or summary)
        ))[:20],
        "rounds": rounds,
        "tools": list(dict.fromkeys(tools_used)),
        "tokens": {
            "prompt": usage_total["prompt_tokens"],
            "completion": usage_total["completion_tokens"],
        },
        "ms": int((time.perf_counter() - started) * 1000),
        "citations": citations,
        "error": error,
    }
    await trace_record(session_id, turn_id, "subagent_done", {
        "id": task_id, "status": status, "rounds": rounds,
        "tools": result["tools"], "ms": result["ms"],
    })
    await _emit({
        "phase": "done",
        "id": task_id,
        "title": title,
        "status": status,
        "summary": result["summary"],
        "findings": result["findings"],
        "files": result["files"],
        "rounds": result["rounds"],
        "tools": result["tools"],
        "tokens": result["tokens"],
        "ms": result["ms"],
        "citations": citations,
        "error": error,
    })
    return result

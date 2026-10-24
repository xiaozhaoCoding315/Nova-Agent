"""Tool registry: schema validation, harness-protected execution, audit.

Contract:
- ``ToolBusinessError`` marks expected user/business failures (bad args,
  quota, risk block). Those are surfaced to the LLM as the tool result and
  are deliberately excluded from circuit-breaker statistics.
- Any other exception is an infrastructure failure: retried by harness,
  counted by the breaker.
"""
import json
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable

import structlog
from fastapi import HTTPException

from app.config import settings
from app.core.harness.config import TIMEOUTS
from app.core.harness.runtime import execute_with_harness
from app.core.security.audit import AuditAction, log_audit
from app.core.security.hooks import run_hook
from app.core.security.policy import PolicyDecision, decide_tool
from app.core.security.redaction import redact_obj, redact_text

logger = structlog.get_logger()


class ToolBusinessError(Exception):
    """Expected failure — never retried, never trips the circuit breaker."""


@dataclass
class ToolContext:
    user: dict
    repo_ids: list[str] = field(default_factory=list)
    repo_roots: dict[str, str] = field(default_factory=dict)
    session_id: str = ""
    permission_mode: str = "auto"   # readonly | ask | auto
    file_ids: list[str] = field(default_factory=list)


@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: dict
    func: Callable[[dict, ToolContext], Awaitable[dict]]
    timeout: int = TIMEOUTS.tool_timeout
    category: str = "read"          # read | write | execute | network
    capabilities: list[str] = field(default_factory=list)


_TYPE_CHECKS = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
}


def validate_args(schema: dict, args: dict) -> str | None:
    """Validate against the JSON-schema subset our tool specs use."""
    if not isinstance(args, dict):
        return "arguments must be an object"

    for required in schema.get("required", []):
        if required not in args:
            return f"missing required argument: {required}"

    props = schema.get("properties", {})
    for key, value in args.items():
        spec = props.get(key)
        if spec is None:
            continue  # additional properties are tolerated
        expected = spec.get("type")
        check = _TYPE_CHECKS.get(expected)
        if check and not check(value):
            return f"argument '{key}' must be of type {expected}"
        if expected == "array" and "items" in spec:
            item_type = spec["items"].get("type")
            item_check = _TYPE_CHECKS.get(item_type)
            if item_check and not all(item_check(i) for i in value):
                return f"argument '{key}' items must be of type {item_type}"
    return None


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    def specs(self) -> list[dict]:
        """OpenAI tools format."""
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in self._tools.values()
        ]

    async def execute(self, name: str, args: dict, ctx: ToolContext) -> dict:
        """Run a tool. Always returns a dict; never raises to the caller.

        Shape: {"ok": bool, "output"|"error": ..., "ms": int, "business": bool}
        """
        tool = self._tools.get(name)
        if tool is None:
            return {"ok": False, "error": f"unknown tool: {name}", "ms": 0, "business": False}

        if isinstance(args, str):
            try:
                args = json.loads(args or "{}")
            except json.JSONDecodeError as exc:
                return {"ok": False, "error": f"invalid JSON arguments: {exc}", "ms": 0, "business": True}

        err = validate_args(tool.parameters, args)
        if err:
            return {"ok": False, "error": err, "ms": 0, "business": True}

        decision = decide_tool(name, tool.category, tool.capabilities, args, ctx)
        if not decision.allowed:
            await self._audit(
                ctx, name, args, ok=False, ms=0, detail=decision.reason,
                action=AuditAction.POLICY_DECISION, decision="deny",
                capabilities=list(decision.capabilities),
            )
            return {
                "ok": False, "error": redact_text(decision.reason),
                "ms": 0, "business": True,
            }

        if settings.tool_pre_hook:
            hook = await run_hook(
                settings.tool_pre_hook,
                self._hook_payload("pre", tool, args, ctx, decision),
                self._hook_cwd(ctx),
            )
            if not hook.allowed:
                await self._audit(
                    ctx, name, args, ok=False, ms=0, detail=f"hook: {hook.detail}",
                    action=AuditAction.HOOK_BLOCKED, decision="hook_blocked",
                    capabilities=list(decision.capabilities),
                )
                return {
                    "ok": False,
                    "error": redact_text(f"前置钩子阻止 {name}：{hook.detail}"),
                    "ms": 0, "business": True,
                }

        start = time.perf_counter()
        try:
            output = await execute_with_harness(
                tool.func,
                args,
                ctx,
                context=f"tool/{name}",
                timeout=tool.timeout,
                use_retry=True,
                use_circuit=True,
                propagate=(ToolBusinessError,),
            )
        except (ToolBusinessError, HTTPException) as exc:
            detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
            ms = int((time.perf_counter() - start) * 1000)
            await self._audit(
                ctx, name, args, ok=False, ms=ms, detail=str(detail),
                decision="allow", capabilities=list(decision.capabilities),
            )
            return {"ok": False, "error": redact_text(str(detail)), "ms": ms, "business": True}
        except Exception as exc:  # noqa: BLE001
            ms = int((time.perf_counter() - start) * 1000)
            logger.warning("tool_failed", tool=name, error=str(exc))
            await self._audit(
                ctx, name, args, ok=False, ms=ms, detail=str(exc),
                decision="allow", capabilities=list(decision.capabilities),
            )
            return {
                "ok": False, "error": redact_text(f"工具执行失败: {exc}"),
                "ms": ms, "business": False,
            }

        ms = int((time.perf_counter() - start) * 1000)
        await self._audit(
            ctx, name, args, ok=True, ms=ms,
            decision="allow", capabilities=list(decision.capabilities),
        )
        result = {"ok": True, "output": redact_obj(output), "ms": ms, "business": False}
        await self._post_hook(tool, args, ctx, decision, result)
        return result

    @staticmethod
    def _hook_cwd(ctx: ToolContext) -> str | None:
        for root in ctx.repo_roots.values():
            if root:
                return root
        return None

    @staticmethod
    def _hook_payload(
        phase: str, tool: ToolDefinition, args: dict, ctx: ToolContext,
        decision: PolicyDecision, result: dict | None = None,
    ) -> dict:
        return {
            "phase": phase,
            "tool": tool.name,
            "category": tool.category,
            "capabilities": list(decision.capabilities),
            "args": redact_obj(args),
            "user": {"id": ctx.user.get("id"), "role": ctx.user.get("role")},
            "repo_ids": ctx.repo_ids,
            "permission_mode": ctx.permission_mode,
            "result": redact_obj(result) if result else None,
        }

    @staticmethod
    async def _post_hook(
        tool: ToolDefinition, args: dict, ctx: ToolContext,
        decision: PolicyDecision, result: dict,
    ) -> None:
        if not settings.tool_post_hook:
            return
        hook = await run_hook(
            settings.tool_post_hook,
            ToolRegistry._hook_payload("post", tool, args, ctx, decision, result),
            ToolRegistry._hook_cwd(ctx),
        )
        if not hook.allowed:
            logger.warning("tool_post_hook_failed", tool=tool.name, detail=hook.detail[:300])

    @staticmethod
    async def _audit(
        ctx: ToolContext, name: str, args: dict, ok: bool, ms: int,
        detail: str = "", action: str = AuditAction.TOOL_CALL,
        decision: str = "allow", capabilities: list[str] | None = None,
    ) -> None:
        try:
            await log_audit(
                action,
                user_id=str(ctx.user.get("id", "")) if ctx.user else "anonymous",
                details={
                    "tool": name, "ok": ok, "ms": ms,
                    "decision": decision,
                    "capabilities": capabilities or [],
                    "args": _preview(args),
                    "detail": detail[:300],
                },
                risk_level="warn" if not ok else "safe",
            )
        except Exception:  # noqa: BLE001
            pass


def _preview(args: dict, limit: int = 500) -> str:
    try:
        text = json.dumps(args, ensure_ascii=False)
    except (TypeError, ValueError):
        text = str(args)
    return redact_text(text[:limit])
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

from app.core.harness.config import TIMEOUTS
from app.core.harness.runtime import execute_with_harness
from app.core.security.audit import AuditAction, log_audit

logger = structlog.get_logger()


class ToolBusinessError(Exception):
    """Expected failure — never retried, never trips the circuit breaker."""


@dataclass
class ToolContext:
    user: dict
    repo_ids: list[str] = field(default_factory=list)


@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: dict
    func: Callable[[dict, ToolContext], Awaitable[dict]]
    timeout: int = TIMEOUTS.tool_timeout


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
            await self._audit(ctx, name, args, ok=False, ms=ms, detail=str(detail))
            return {"ok": False, "error": str(detail), "ms": ms, "business": True}
        except Exception as exc:  # noqa: BLE001
            ms = int((time.perf_counter() - start) * 1000)
            logger.warning("tool_failed", tool=name, error=str(exc))
            await self._audit(ctx, name, args, ok=False, ms=ms, detail=str(exc))
            return {"ok": False, "error": f"工具执行失败: {exc}", "ms": ms, "business": False}

        ms = int((time.perf_counter() - start) * 1000)
        await self._audit(ctx, name, args, ok=True, ms=ms)
        return {"ok": True, "output": output, "ms": ms, "business": False}

    @staticmethod
    async def _audit(ctx: ToolContext, name: str, args: dict, ok: bool, ms: int, detail: str = "") -> None:
        try:
            await log_audit(
                AuditAction.TOOL_CALL,
                user_id=str(ctx.user.get("id", "")) if ctx.user else "anonymous",
                details={"tool": name, "ok": ok, "ms": ms, "args": _preview(args), "detail": detail[:300]},
                risk_level="warn" if not ok else "safe",
            )
        except Exception:  # noqa: BLE001
            pass


def _preview(args: dict, limit: int = 500) -> str:
    try:
        text = json.dumps(args, ensure_ascii=False)
    except (TypeError, ValueError):
        text = str(args)
    return text[:limit]
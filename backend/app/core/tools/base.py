"""Agent Skill tool framework: registry, argument validation, harness-wrapped execution."""
import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import structlog

from app.core.harness.config import TIMEOUTS
from app.core.harness.runtime import execute_with_harness

logger = structlog.get_logger()


@dataclass
class Tool:
    """A single agent skill: JSON-Schema described, async-executed tool."""

    name: str
    description: str
    parameters: dict  # JSON Schema, OpenAI function-calling format
    handler: Callable[..., Awaitable[Any]]

    def to_openai_spec(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolError(Exception):
    """Invalid tool usage: unknown tool, malformed arguments, rejected input."""


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ToolError(f"duplicate tool registration: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        tool = self._tools.get(name)
        if tool is None:
            raise ToolError(f"unknown tool: {name}")
        return tool

    def names(self) -> list[str]:
        return sorted(self._tools)

    def to_openai_tools(self) -> list[dict]:
        return [t.to_openai_spec() for t in self._tools.values()]


def validate_arguments(tool: Tool, raw: str | dict | None) -> dict:
    """Parse + structurally validate tool arguments (required fields only)."""
    if raw is None or raw == "":
        raw = {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ToolError(f"invalid JSON arguments for {tool.name}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ToolError(f"arguments for {tool.name} must be a JSON object")
    for required in tool.parameters.get("required", []):
        if required not in raw:
            raise ToolError(f"missing required argument '{required}' for {tool.name}")
    return raw


async def run_tool(name: str, raw_arguments: str | dict | None) -> dict:
    """Unified tool entry point.

    Contract: never raises — always returns a normalised dict so a failing
    tool can never break the chat loop. Execution is wrapped by the harness
    (timeout + retry + circuit breaker), consistent with retrieval / LLM calls.
    """
    try:
        tool = registry.get(name)
        args = validate_arguments(tool, raw_arguments)
    except ToolError as exc:
        return {"ok": False, "tool": name, "error": str(exc)}

    async def _fallback(*_a, **_kw) -> dict:
        return {"ok": False, "tool": name, "error": "tool execution failed after retries"}

    try:
        result = await execute_with_harness(
            tool.handler,
            **args,
            context=f"tool/{name}",
            timeout=TIMEOUTS.tool_timeout,
            use_retry=True,
            fallback=_fallback,
            propagate=(ToolError, ValueError),
        )
    except (ToolError, ValueError) as exc:
        # business validation errors keep their original message for the LLM
        logger.info("tool_rejected", tool=name, error=str(exc))
        return {"ok": False, "tool": name, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001 — tool errors must not break the chat loop
        logger.warning("tool_failed", tool=name, error=str(exc))
        return {"ok": False, "tool": name, "error": str(exc)}

    payload = result if isinstance(result, dict) else {"value": result}
    payload.setdefault("ok", True)
    payload.setdefault("tool", name)
    return payload


registry = ToolRegistry()

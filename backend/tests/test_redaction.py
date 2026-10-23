"""Secret redaction for output, traces and audit previews."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.memory.context import build_system_prompt
from app.core.security.redaction import REDACTED, redact_obj, redact_text
from app.core.tools import base as tools_base
from app.core.tools.base import ToolContext, ToolDefinition, ToolRegistry
from app.core import trace as trace_mod


def test_redacts_common_secret_shapes():
    text = (
        "key sk-abcdefghijklmnop1234\n"
        "ark-1234567890abcdefgh\n"
        "AWS AKIAIOSFODNN7EXAMPLE\n"
        "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payloadsignaturepart.x\n"
        "DASHSCOPE_API_KEY=super-secret-value\n"
        "-----BEGIN RSA PRIVATE KEY-----\nabc\n-----END RSA PRIVATE KEY-----"
    )
    cleaned = redact_text(text)
    for leaked in ("sk-abcdefghijklmnop1234", "ark-1234567890abcdefgh", "super-secret-value", "abc\n"):
        assert leaked not in cleaned
    assert "DASHSCOPE_API_KEY=" + REDACTED in cleaned
    assert REDACTED in cleaned


def test_redact_obj_is_recursive():
    payload = {"nested": [{"token": "sk-abcdefghijklmnop1234"}], "ok": 1}
    cleaned = redact_obj(payload)
    assert "sk-abcdefghijklmnop1234" not in str(cleaned)
    assert cleaned["ok"] == 1


@pytest.mark.asyncio
async def test_tool_output_is_redacted_before_return(monkeypatch):
    monkeypatch.setattr(tools_base, "log_audit", AsyncMock())
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="leak", description="", parameters={},
        func=AsyncMock(return_value={"stdout": "token=sk-abcdefghijklmnop1234"}),
        category="read", capabilities=["fs.read"],
    ))

    result = await registry.execute("leak", {}, ToolContext(user={"id": 1, "role": "admin"}))

    assert result["ok"] is True
    assert "sk-abcdefghijklmnop1234" not in str(result["output"])
    assert REDACTED in str(result["output"])


@pytest.mark.asyncio
async def test_trace_payload_is_redacted(monkeypatch):
    execute = AsyncMock()
    monkeypatch.setattr(trace_mod, "execute", execute)

    await trace_mod.record(
        "s1", "t1", "tool_result",
        {"preview": "DASHSCOPE_API_KEY=super-secret-value"},
    )

    _, params = execute.await_args.args
    assert "super-secret-value" not in params[3]
    assert REDACTED in params[3]


def test_context_snippets_and_facts_are_redacted():
    hit = SimpleNamespace(
        path="app/config.py", line_start=1, line_end=2, lang="python",
        content="DASHSCOPE_API_KEY=super-secret-value",
    )
    prompt = build_system_prompt([hit], ["key sk-abcdefghijklmnop1234"])
    assert "super-secret-value" not in prompt
    assert "sk-abcdefghijklmnop1234" not in prompt
    assert REDACTED in prompt

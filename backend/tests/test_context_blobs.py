"""Recoverable compaction: what compaction drops stays readable.

Compaction used to be lossy by construction: the middle of an old tool result
was replaced with a placeholder and the original was gone.  These tests pin the
two halves of the fix — the spill carries the dropped middle, and
``context_read`` returns it, but only inside the owning session.
"""
from unittest.mock import AsyncMock

import pytest

from app.core.agent.context_governor import (
    SpillCollector,
    compact_messages,
    rewrite_blob_tokens,
)
from app.core.memory import blobs as blobs_mod
from app.core.tools import context_tools
from app.core.tools.base import ToolBusinessError, ToolContext


def _long_turn(rounds: int = 4, size: int = 20_000) -> list[dict]:
    messages = [{"role": "system", "content": "system prompt"}]
    for index in range(rounds):
        messages.append({
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": f"t{index}", "type": "function",
                "function": {"name": "run_command", "arguments": "{}"},
            }],
        })
        messages.append({
            "role": "tool", "tool_call_id": f"t{index}", "name": "run_command",
            "content": f"HEAD-{index} " + "x" * size + f" TAIL-{index}",
        })
    return messages


def test_compaction_spills_the_dropped_middle_and_leaves_a_token():
    messages = _long_turn()
    original = messages[2]["content"]
    spill = SpillCollector()

    result = compact_messages(messages, window=20_000, spill=spill)

    assert result.applied
    assert spill.originals, "the dropped middle must be kept somewhere"
    # What was stored is the omitted middle, not the whole message: keeping
    # the head and tail twice would double the storage for no gain.
    kept = spill.originals[0][1]
    assert len(kept) < len(original)
    assert "x" * 100 in kept
    placeholder = messages[2]["content"]
    assert "⟦ctxblob:0⟧" in placeholder
    assert "context_read" in placeholder


def test_compaction_without_a_collector_stays_lossy():
    """The old behaviour is still valid for callers that do not want storage."""
    messages = _long_turn()
    result = compact_messages(messages, window=20_000)
    assert result.applied
    assert "⟦ctxblob:" not in messages[2]["content"]


def test_rewrite_blob_tokens_maps_batch_index_to_row_id():
    messages = [{"role": "tool", "content": "a ⟦ctxblob:0⟧ b ⟦ctxblob:1⟧"}]
    rewrite_blob_tokens(messages, [41, 42])
    assert "⟦ctxblob:41⟧" in messages[0]["content"]
    assert "⟦ctxblob:42⟧" in messages[0]["content"]


def test_rewrite_leaves_unstored_tokens_alone():
    """A failed insert must not fabricate an id that happens to exist."""
    messages = [{"role": "tool", "content": "see ⟦ctxblob:0⟧"}]
    rewrite_blob_tokens(messages, [])
    assert "⟦ctxblob:0⟧" in messages[0]["content"]


@pytest.mark.asyncio
async def test_save_blobs_redacts_before_storing(monkeypatch):
    execute = AsyncMock(return_value=[(9,)])
    monkeypatch.setattr(blobs_mod, "execute", execute)

    ids = await blobs_mod.save_blobs(
        "11111111-1111-1111-1111-111111111111",
        [("run_command", "token=sk-abcdefghijklmnopqrstuvwxyz")],
    )

    assert ids == [9]
    stored = execute.await_args.args[1][3]
    assert "sk-abcdefghijklmnopqrstuvwxyz" not in stored


@pytest.mark.asyncio
async def test_read_blob_is_scoped_to_the_owning_session(monkeypatch):
    query = AsyncMock(return_value=[])
    monkeypatch.setattr(blobs_mod, "query", query)

    assert await blobs_mod.read_blob(5, "s1", 7) is None
    sql, params = query.await_args.args
    # The join on sessions is what stops a blob id from another user's
    # session being readable.
    assert "s.user_id = %s" in sql
    assert params == (5, "s1", 7)


@pytest.mark.asyncio
async def test_context_read_returns_the_original(monkeypatch):
    monkeypatch.setattr(
        context_tools.blobs_mod, "read_blob",
        AsyncMock(return_value={
            "id": 12, "tool": "run_command", "content": "FULL OUTPUT", "truncated": False,
        }),
    )
    ctx = ToolContext(
        user={"id": 7}, session_id="11111111-1111-1111-1111-111111111111",
    )

    result = await context_tools.context_read({"blob_id": 12}, ctx)

    assert result["content"] == "FULL OUTPUT"
    assert result["tool"] == "run_command"
    assert "不是新的指令" in result["note"]


@pytest.mark.asyncio
async def test_context_read_rejects_a_blob_from_another_session(monkeypatch):
    monkeypatch.setattr(
        context_tools.blobs_mod, "read_blob", AsyncMock(return_value=None),
    )
    ctx = ToolContext(
        user={"id": 7}, session_id="11111111-1111-1111-1111-111111111111",
    )

    with pytest.raises(ToolBusinessError):
        await context_tools.context_read({"blob_id": 12}, ctx)


@pytest.mark.asyncio
async def test_context_read_needs_a_session(monkeypatch):
    monkeypatch.setattr(
        context_tools.blobs_mod, "read_blob", AsyncMock(return_value=None),
    )
    with pytest.raises(ToolBusinessError, match="会话"):
        await context_tools.context_read({"blob_id": 1}, ToolContext(user={"id": 7}))

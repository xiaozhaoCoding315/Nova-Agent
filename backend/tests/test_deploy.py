"""Preview deployment helpers and idempotency ledger."""
from unittest.mock import AsyncMock

import pytest

from app.core.deploy import ledger, service


@pytest.mark.asyncio
async def test_ledger_begin_returns_existing_action(monkeypatch):
    existing = (
        "a1", 1, "key", "deploy", "repo", "succeeded",
        {}, {"url": "http://127.0.0.1:1"}, None, None, None, None,
    )
    monkeypatch.setattr(ledger, "query", AsyncMock(return_value=[existing]))
    action = await ledger.begin(1, "key", "deploy", "repo", {})
    assert action["status"] == "succeeded"
    assert action["response"]["url"] == "http://127.0.0.1:1"


@pytest.mark.asyncio
async def test_ledger_begin_inserts_pending(monkeypatch):
    monkeypatch.setattr(ledger, "query", AsyncMock(return_value=[]))
    execute = AsyncMock()
    monkeypatch.setattr(ledger, "execute", execute)
    monkeypatch.setattr(ledger, "get", AsyncMock(return_value=None))

    action = await ledger.begin(1, "key", "deploy", "repo", {"repo_id": "r1"})

    assert action["status"] == "pending"
    assert "INSERT INTO external_actions" in execute.await_args.args[0]


def test_preview_config_defaults_and_overrides():
    command, health = service._preview_config({})
    assert "uvicorn app.main:app" in command
    assert health == "/health"

    command, health = service._preview_config({
        "nova.yaml": "preview:\n  command: uvicorn app.main:app --port 8000\n  health: /ready\n"
    })
    assert command == "uvicorn app.main:app --port 8000"
    assert health == "/ready"


def test_free_port_is_valid():
    port = service._free_port()
    assert 1 <= port <= 65535

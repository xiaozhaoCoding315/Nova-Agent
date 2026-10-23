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


def test_preview_config_detects_python():
    spec = service._preview_config({"app/main.py": "print(1)"})
    assert spec.runtime == "python"
    assert "uvicorn app.main:app" in spec.command
    assert spec.port == 8000
    assert spec.health == "/health"


def test_preview_config_detects_node_start_script():
    spec = service._preview_config({
        "package.json": '{"scripts": {"start": "node serve.js"}}',
    })
    assert spec.runtime == "node"
    assert spec.command == "npm start"
    assert spec.port == 3000
    assert spec.health == "/"


def test_preview_config_overrides_runtime_and_port():
    spec = service._preview_config({
        "app/main.py": "print(1)",
        "package.json": '{"scripts": {"start": "node serve.js"}}',
        "nova.yaml": (
            "preview:\n"
            "  runtime: node\n"
            "  command: node frontend/scripts/serve.js\n"
            "  port: 3100\n"
            "  health: /ready\n"
        ),
    })
    assert spec.runtime == "node"
    assert spec.command == "node frontend/scripts/serve.js"
    assert spec.port == 3100
    assert spec.health == "/ready"


def test_node_preview_requires_start_or_command():
    with pytest.raises(service.DeployError, match="start"):
        service._preview_config({"package.json": '{"scripts": {}}'})


def test_preview_rejects_invalid_port():
    with pytest.raises(service.DeployError, match="端口"):
        service._preview_config({
            "app/main.py": "print(1)",
            "nova.yaml": "preview:\n  port: 70000\n",
        })


def test_free_port_is_valid():
    port = service._free_port()
    assert 1 <= port <= 65535


@pytest.mark.asyncio
async def test_cleanup_expired_stops_old_running(monkeypatch):
    from app import db

    monkeypatch.setattr(service.settings, "preview_ttl_minutes", 60)
    query = AsyncMock(return_value=[("d1", 1)])
    monkeypatch.setattr(db, "query", query)
    teardown = AsyncMock(return_value={})
    monkeypatch.setattr(service, "teardown_preview", teardown)

    assert await service.cleanup_expired() == 1
    teardown.assert_awaited_once()
    assert "make_interval" in query.await_args.args[0]


@pytest.mark.asyncio
async def test_cleanup_expired_disabled(monkeypatch):
    monkeypatch.setattr(service.settings, "preview_ttl_minutes", 0)
    assert await service.cleanup_expired() == 0

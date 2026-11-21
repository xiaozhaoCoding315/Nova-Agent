"""Remote workbench: pairing, signed commands, stop, revoke and redaction."""
from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

from app.config import settings
from app.core.remote.contracts import CommandEnvelope
from app.core.remote.identity import (
    canonical_command_payload,
    public_jwk_from_private,
)
from app.core.remote.redact import redact_text


def _client(user_id: int = 7):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.v1 import remote as remote_api
    from app.core.security.auth import get_current_user

    app = FastAPI()
    app.include_router(remote_api.router)
    app.dependency_overrides[get_current_user] = lambda: {"id": user_id}
    return TestClient(app)


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _signature(private_key, envelope: CommandEnvelope) -> str:
    return _b64(private_key.sign(canonical_command_payload(envelope), ec.ECDSA(hashes.SHA256())))


def _envelope(
    device_id: str,
    intent: str,
    private_key,
    *,
    command_id: str = "cmd-1",
    nonce: str = "nonce-1",
    ttl_seconds: int = 30,
    approval_id: str = "",
    action_hash: str = "",
    decision: str = "",
) -> dict:
    now = datetime.now(timezone.utc)
    envelope = CommandEnvelope(
        command_id=command_id,
        device_id=device_id,
        type=intent,  # type: ignore[arg-type]
        nonce=nonce,
        issued_at=now.isoformat(),
        expires_at=(now + timedelta(seconds=ttl_seconds)).isoformat(),
        signature="",
        approval_id=approval_id,
        action_hash=action_hash,
        decision=decision,
    )
    envelope.signature = _signature(private_key, envelope)
    return envelope.to_dict()


@pytest.fixture()
def api(tmp_path: Path, monkeypatch):
    from app.core.remote import service as remote_service

    monkeypatch.setattr(settings, "user_data_dir", str(tmp_path / "data"))
    monkeypatch.setattr(settings, "remote_enabled", True)
    remote_service.replay_store().clear()
    return _client()


@pytest.fixture()
def phone():
    private = ec.generate_private_key(ec.SECP256R1())
    return private, public_jwk_from_private(private)


def _pair(api, phone, *, name: str = "我的手机") -> tuple[dict, dict]:
    private, jwk = phone
    created = api.post("/remote/pairings", json={})
    assert created.status_code == 200, created.text
    body = created.json()
    claim = api.post("/remote/pair/claim", json={
        "pair_id": body["pairing"]["pair_id"],
        "token": body["token"],
        "device_name": name,
        "public_key": jwk,
    })
    assert claim.status_code == 200, claim.text
    confirmed = api.post(
        f"/remote/pairings/{body['pairing']['pair_id']}/confirm",
        json={"sas": claim.json()["sas"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    return body, confirmed.json()["device"]


def test_pairing_requires_sas_and_binds_once(api, phone):
    private, jwk = phone
    created = api.post("/remote/pairings", json={}).json()
    pair_id = created["pairing"]["pair_id"]
    assert "/m#pair_id=" in created["link"]
    assert created["token"] not in created["link"].split("#")[0]

    claim = api.post("/remote/pair/claim", json={
        "pair_id": pair_id,
        "token": created["token"],
        "device_name": "手机 A",
        "public_key": jwk,
    })
    assert claim.status_code == 200, claim.text
    claimed = claim.json()
    assert claimed["status"] == "pending_confirmation"
    assert claimed["sas"].replace(" ", "").isdigit()

    polled = api.get(f"/remote/pairings/{pair_id}").json()
    assert polled["pairing"]["sas"] == claimed["sas"]
    assert polled["device"]["status"] == "pending"

    wrong = api.post(f"/remote/pairings/{pair_id}/confirm", json={"sas": "000 000"})
    assert wrong.status_code == 400
    assert "验证串" in wrong.json()["detail"]

    rejected = api.post("/remote/pair/claim", json={
        "pair_id": pair_id,
        "token": created["token"],
        "device_name": "手机 B",
        "public_key": jwk,
    })
    assert rejected.status_code == 400
    assert "已被使用" in rejected.json()["detail"]

    confirmed = api.post(
        f"/remote/pairings/{pair_id}/confirm", json={"sas": claimed["sas"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["device"]["status"] == "active"
    assert api.get("/remote/devices").json()["devices"][0]["status"] == "active"


def test_expired_pairing_is_refused(api, phone):
    _, jwk = phone
    created = api.post("/remote/pairings", json={"ttl_seconds": 60}).json()
    pair_id = created["pairing"]["pair_id"]
    path = Path(settings.user_data_dir) / "remote" / "pairings" / f"{pair_id}.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["expires_at"] = (
        datetime.now(timezone.utc) - timedelta(seconds=5)
    ).isoformat()
    path.write_text(json.dumps(record), encoding="utf-8")

    response = api.post("/remote/pair/claim", json={
        "pair_id": pair_id,
        "token": created["token"],
        "public_key": jwk,
    })
    assert response.status_code == 400
    assert "过期" in response.json()["detail"]


def test_pending_device_sees_only_pairing_state(api, phone):
    private, jwk = phone
    created = api.post("/remote/pairings", json={}).json()
    claim = api.post("/remote/pair/claim", json={
        "pair_id": created["pairing"]["pair_id"],
        "token": created["token"],
        "public_key": jwk,
    }).json()

    pending = api.post("/remote/commands", json=_envelope(
        claim["device_id"], "status.get", private, nonce="pending-1",
    ))
    assert pending.status_code == 200, pending.text
    body = pending.json()
    assert body["device_status"] == "pending_confirmation"
    assert body["pairing"]["sas"] == claim["sas"]
    assert "events" not in body

    stop = api.post("/remote/commands", json=_envelope(
        claim["device_id"], "run.stop", private, nonce="pending-2",
    ))
    assert stop.status_code == 200
    assert stop.json()["ok"] is False
    assert stop.json()["decision"]["requires_local"] is True


def test_signed_status_redacts_paths_and_secrets(api, phone, monkeypatch):
    from app.core.remote import service as remote_service

    _, device = _pair(api, phone)
    private, _ = phone

    async def fake_query(sql: str, params: tuple):
        if "FROM turns" in sql:
            return [("turn-1", "session-1", "running", datetime.now(timezone.utc))]
        return [("tool_output", {
            "text": "reading C:\\Users\\alice\\client\\secret.py with sk-abcdefgh12345678",
            "stage": "执行测试",
            "percent": 40,
        })]

    monkeypatch.setattr(remote_service, "query", fake_query)
    response = api.post("/remote/commands", json=_envelope(
        device["device_id"], "status.get", private, nonce="status-1",
    ))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["device_status"] == "active"
    event = body["events"][0]
    assert event["task_id"] == "turn-1"
    assert event["percent"] == 40
    assert "C:\\Users" not in event["summary"]
    assert "sk-abc" not in event["summary"]
    assert "正在执行工具" == event["summary"]

    audit = api.get("/remote/audit").json()
    assert any(item["type"] == "status.get" for item in audit["local"])
    assert any(item["type"] == "status.get" for item in audit["relay"])
    assert "summary" not in audit["relay"][0]


def test_stop_is_signed_idempotent_and_revocation_is_immediate(api, phone, monkeypatch):
    from app.core.remote import service as remote_service

    _, device = _pair(api, phone)
    private, _ = phone
    active = {"turn-1": "running"}

    async def fake_query(sql: str, params: tuple):
        return [("turn-1", None)] if "FROM turns" in sql else []

    async def fake_cancel(turn_id: str):
        if turn_id in active:
            active.pop(turn_id)
            return "running"
        return None

    monkeypatch.setattr(remote_service, "query", fake_query)
    monkeypatch.setattr(remote_service.turn_store, "request_cancel", fake_cancel)

    first = api.post("/remote/commands", json=_envelope(
        device["device_id"], "run.stop", private, nonce="stop-1", command_id="stop-1",
    ))
    assert first.status_code == 200, first.text
    assert first.json()["stopped_task_ids"] == ["turn-1"]

    second = api.post("/remote/commands", json=_envelope(
        device["device_id"], "run.stop", private, nonce="stop-2", command_id="stop-2",
    ))
    assert second.json()["stopped_task_ids"] == []
    assert second.json()["idempotent"] is True

    replay = api.post("/remote/commands", json=_envelope(
        device["device_id"], "run.stop", private, nonce="stop-1", command_id="stop-1",
    ))
    assert replay.json()["ok"] is False
    assert "nonce" in replay.json()["decision"]["reason"]

    revoked = api.post(f"/remote/devices/{device['device_id']}/revoke")
    assert revoked.status_code == 200
    after = api.post("/remote/commands", json=_envelope(
        device["device_id"], "status.get", private, nonce="status-2",
    ))
    assert after.json()["ok"] is False
    assert "撤销" in after.json()["decision"]["reason"]


def test_cross_user_cannot_read_pairing_or_revoke(api, phone):
    created = api.post("/remote/pairings", json={}).json()
    other = _client(8)
    assert other.get(f"/remote/pairings/{created['pairing']['pair_id']}").status_code == 404
    _, device = _pair(api, phone)
    assert other.post(f"/remote/devices/{device['device_id']}/revoke").status_code == 404
    assert other.get("/remote/devices").json()["devices"] == []


def test_remote_approval_list_and_decide(api, phone, monkeypatch):
    from app.core import approvals as local_approvals
    from app.core.remote import approvals as remote_approvals
    from app.core.remote import service as remote_service

    _, device = _pair(api, phone)
    private, _ = phone

    async def fake_query(sql: str, params: tuple):
        return []

    monkeypatch.setattr(remote_service, "query", fake_query)
    record = remote_approvals.register(
        user_id=7,
        session_id="session-1",
        task_id="turn-1",
        tool_call_id="tool-1",
        tool_name="write_files",
        args={"path": "src/x.ts"},
        reason="写入文件",
    )
    assert record is not None
    assert record["remote_decidable"] is True

    resolved: list[tuple] = []
    monkeypatch.setattr(
        local_approvals, "resolve",
        lambda session_id, tool_call_id, user_id, approved: (
            resolved.append((session_id, tool_call_id, user_id, approved)) or True
        ),
    )

    listed = api.post("/remote/commands", json=_envelope(
        device["device_id"], "status.get", private, nonce="approval-list",
    ))
    assert listed.status_code == 200, listed.text
    approvals = listed.json()["approvals"]
    assert approvals[0]["approval_id"] == "tool-1"
    assert approvals[0]["action_hash"] == record["action_hash"]
    assert "path" not in approvals[0]

    decided = api.post("/remote/commands", json=_envelope(
        device["device_id"], "approval.decide", private, nonce="approval-1",
        approval_id="tool-1", action_hash=record["action_hash"], decision="approve",
    ))
    assert decided.status_code == 200, decided.text
    assert decided.json()["ok"] is True
    assert decided.json()["approval"]["status"] == "approved"
    assert resolved == [("session-1", "tool-1", 7, True)]

    again = api.post("/remote/commands", json=_envelope(
        device["device_id"], "approval.decide", private, nonce="approval-2",
        approval_id="tool-1", action_hash=record["action_hash"], decision="approve",
    ))
    assert again.json()["ok"] is False
    assert "处理过" in again.json()["decision"]["reason"]


def test_high_risk_approval_is_never_remote_decidable(api, phone, monkeypatch):
    from app.core.remote import approvals as remote_approvals
    from app.core.remote import service as remote_service

    _, device = _pair(api, phone)
    private, _ = phone

    async def fake_query(sql: str, params: tuple):
        return []

    monkeypatch.setattr(remote_service, "query", fake_query)
    record = remote_approvals.register(
        user_id=7,
        session_id="session-2",
        task_id="turn-2",
        tool_call_id="tool-2",
        tool_name="local_exec",
        args={"command": "rm -rf /"},
    )
    assert record is not None
    assert record["risk"] == "high"
    assert record["remote_decidable"] is False

    response = api.post("/remote/commands", json=_envelope(
        device["device_id"], "approval.decide", private, nonce="high-1",
        approval_id="tool-2", action_hash=record["action_hash"], decision="approve",
    ))
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["decision"]["requires_local"] is True
    listed = api.post("/remote/commands", json=_envelope(
        device["device_id"], "status.get", private, nonce="high-list",
    )).json()["approvals"]
    assert listed[0]["remote_decidable"] is False


def test_completion_notification_is_redacted(api, phone):
    from app.core.remote import store
    from app.core.remote.service import notify_turn_finished

    _pair(api, phone)
    notify_turn_finished(7, "turn-9", "succeeded")
    notify_turn_finished(7, "turn-9", "succeeded")
    completed = [
        item for item in store.list_notifications(7) if item["kind"] == "completed"
    ]
    assert len(completed) == 1
    assert completed[0]["summary"] == "任务已完成"
    assert "turn-9" in completed[0]["task_id"]

    assert api.get("/remote/notifications?unread_only=true").json()["unread"] >= 1
    read = api.post("/remote/notifications/read", json={})
    assert read.status_code == 200
    assert api.get("/remote/notifications?unread_only=true").json()["unread"] == 0


def test_remote_disabled_returns_404(api, monkeypatch):
    monkeypatch.setattr(settings, "remote_enabled", False)
    assert api.get("/remote/config").status_code == 404


def test_redact_text_removes_paths_credentials_and_links():
    raw = (
        "读取 C:\\Users\\alice\\secret.py 和 /home/bob/project/.env，"
        "token=sk-abcdefgh12345678 见 https://example.com/a?b=1 "
        "联系 alice@example.com"
    )
    cleaned = redact_text(raw)
    assert "C:\\Users" not in cleaned
    assert "/home/bob" not in cleaned
    assert "sk-abc" not in cleaned
    assert "https://" not in cleaned
    assert "alice@example.com" not in cleaned
    assert "……" not in cleaned

"""Contract tests for the remote workbench (M1)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.core.remote.contracts import (
    ApprovalRequest,
    CommandEnvelope,
    DeviceInfo,
    ProgressEvent,
)
from app.core.remote.crypto import sign_hmac, verify_hmac
from app.core.remote.policy import InMemoryReplayStore, validate_command


NOW = datetime(2026, 11, 21, 12, 0, 0, tzinfo=timezone.utc)


def _device(**overrides) -> DeviceInfo:
    values = {
        "device_id": "device-1",
        "name": "phone",
        "public_key": "test-public-key",
        "permissions": ["status", "stop", "approve", "resume", "answer"],
    }
    values.update(overrides)
    return DeviceInfo(**values)


def _envelope(
    *,
    intent: str = "status.get",
    ttl: int = 30,
    nonce: str = "nonce-1",
    signature: str = "signature",
    action_hash: str = "",
    issued_at: str | None = None,
    expires_at: str | None = None,
) -> CommandEnvelope:
    return CommandEnvelope(
        command_id="command-1",
        device_id="device-1",
        type=intent,  # type: ignore[arg-type]
        nonce=nonce,
        issued_at=issued_at or NOW.isoformat(),
        expires_at=expires_at or (NOW + timedelta(seconds=ttl)).isoformat(),
        signature=signature,
        action_hash=action_hash,
    )


def _approval(**overrides) -> ApprovalRequest:
    values = {
        "approval_id": "approval-1",
        "task_id": "task-1",
        "action_hash": "action-hash-1",
        "title": "写入 src/app.py",
        "risk": "medium",
        "expires_at": (NOW + timedelta(minutes=5)).isoformat(),
    }
    values.update(overrides)
    return ApprovalRequest(**values)


def _verify_ok(_: CommandEnvelope) -> bool:
    return True


def test_valid_status_command_is_allowed() -> None:
    decision = validate_command(
        _envelope(),
        device=_device(),
        verify_signature=_verify_ok,
        now=NOW,
    )
    assert decision.allowed
    assert decision.status == "allowed"
    assert decision.risk == "low"


def test_expired_command_is_denied() -> None:
    command = _envelope(
        issued_at=(NOW - timedelta(seconds=90)).isoformat(),
        expires_at=(NOW - timedelta(seconds=1)).isoformat(),
    )
    decision = validate_command(
        command,
        device=_device(),
        verify_signature=_verify_ok,
        now=NOW,
    )
    assert not decision.allowed
    assert "expired" in decision.reason


def test_command_ttl_over_sixty_seconds_is_denied() -> None:
    command = _envelope(ttl=61)
    decision = validate_command(
        command,
        device=_device(),
        verify_signature=_verify_ok,
        now=NOW,
    )
    assert not decision.allowed
    assert "60 second" in decision.reason


def test_future_command_is_denied() -> None:
    command = _envelope(
        issued_at=(NOW + timedelta(minutes=2)).isoformat(),
        expires_at=(NOW + timedelta(minutes=3)).isoformat(),
    )
    decision = validate_command(
        command,
        device=_device(),
        verify_signature=_verify_ok,
        now=NOW,
    )
    assert not decision.allowed
    assert "future" in decision.reason


def test_revoked_device_is_denied() -> None:
    decision = validate_command(
        _envelope(),
        device=_device(revoked_at=NOW.isoformat()),
        verify_signature=_verify_ok,
        now=NOW,
    )
    assert not decision.allowed
    assert "revoked" in decision.reason


def test_device_without_permission_is_denied() -> None:
    decision = validate_command(
        _envelope(intent="run.stop"),
        device=_device(permissions=["status"]),
        verify_signature=_verify_ok,
        now=NOW,
    )
    assert not decision.allowed
    assert "permission" in decision.reason


def test_missing_signature_verifier_is_denied() -> None:
    decision = validate_command(
        _envelope(),
        device=_device(),
        verify_signature=None,
        now=NOW,
    )
    assert not decision.allowed
    assert "verification is not configured" in decision.reason


def test_failed_signature_is_denied() -> None:
    decision = validate_command(
        _envelope(),
        device=_device(),
        verify_signature=lambda _: False,
        now=NOW,
    )
    assert not decision.allowed
    assert "signature verification failed" in decision.reason


def test_replayed_nonce_is_denied() -> None:
    store = InMemoryReplayStore()
    first = validate_command(
        _envelope(nonce="nonce-replay"),
        device=_device(),
        verify_signature=_verify_ok,
        replay_store=store,
        now=NOW,
    )
    second = validate_command(
        _envelope(nonce="nonce-replay"),
        device=_device(),
        verify_signature=_verify_ok,
        replay_store=store,
        now=NOW,
    )
    assert first.allowed
    assert not second.allowed
    assert "nonce" in second.reason


def test_approval_decision_must_bind_action_hash() -> None:
    decision = validate_command(
        _envelope(intent="approval.decide", action_hash="wrong-action"),
        device=_device(),
        verify_signature=_verify_ok,
        approval=_approval(),
        now=NOW,
    )
    assert not decision.allowed
    assert "action hash" in decision.reason


def test_high_risk_approval_cannot_be_decided_remotely() -> None:
    decision = validate_command(
        _envelope(intent="approval.decide", action_hash="action-hash-1"),
        device=_device(),
        verify_signature=_verify_ok,
        approval=_approval(risk="high"),
        now=NOW,
    )
    assert not decision.allowed
    assert decision.requires_local
    assert "high risk" in decision.reason


def test_medium_risk_approval_can_be_decided_remotely() -> None:
    decision = validate_command(
        _envelope(intent="approval.decide", action_hash="action-hash-1"),
        device=_device(),
        verify_signature=_verify_ok,
        approval=_approval(),
        now=NOW,
    )
    assert decision.allowed
    assert decision.risk == "medium"


def test_expired_approval_cannot_be_decided_remotely() -> None:
    decision = validate_command(
        _envelope(intent="approval.decide", action_hash="action-hash-1"),
        device=_device(),
        verify_signature=_verify_ok,
        approval=_approval(expires_at=(NOW - timedelta(seconds=1)).isoformat()),
        now=NOW,
    )
    assert not decision.allowed
    assert "expired" in decision.reason


def test_resume_requires_local_policy_opt_in() -> None:
    blocked = validate_command(
        _envelope(intent="run.resume"),
        device=_device(),
        verify_signature=_verify_ok,
        now=NOW,
    )
    allowed = validate_command(
        _envelope(intent="run.resume"),
        device=_device(),
        verify_signature=_verify_ok,
        now=NOW,
        allow_resume=True,
    )
    assert not blocked.allowed
    assert blocked.requires_local
    assert allowed.allowed


def test_hmac_signature_roundtrip_and_tamper_detection() -> None:
    secret = b"test-secret"
    command = _envelope()
    command.signature = sign_hmac(secret, command)
    assert verify_hmac(secret, command)
    command.args_ciphertext = "tampered"
    assert not verify_hmac(secret, command)


def test_progress_event_serializes_only_redacted_fields() -> None:
    event = ProgressEvent(
        event_id="e1",
        task_id="t1",
        status="running",
        stage="drafting",
        percent=40,
        summary="正在起草第 2 章",
    )
    payload = event.to_dict()
    assert payload["summary"] == "正在起草第 2 章"
    assert "source_code" not in payload
    assert "api_key" not in payload
    assert "stdout" not in payload

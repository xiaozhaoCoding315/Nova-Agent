"""Local policy for remote commands.

The remote workbench never gets a second execution path.  Every command is
validated here and then mapped to the existing local approval chain.  M1
contains no relay or listener; it pins the contract and the denial cases that
M2/M3 will exercise over the wire.
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from typing import Callable

from app.core.remote.contracts import (
    MAX_INSTRUCTION_CHARS,
    ApprovalRequest,
    CommandDecision,
    CommandEnvelope,
    DeviceInfo,
    RiskLevel,
    parse_timestamp,
    utc_now,
)

INTENT_RISK: dict[str, RiskLevel] = {
    "status.get": "low",
    "run.stop": "low",
    "approval.list": "low",
    "approval.decide": "medium",
    "run.resume": "medium",
    "answer.select": "medium",
    # Queued for the desktop to review; never executed straight from the phone.
    "chat.instruct": "medium",
}

INTENT_PERMISSION: dict[str, str] = {
    "status.get": "status",
    "run.stop": "stop",
    "approval.list": "approve",
    "approval.decide": "approve",
    # "approve" keeps already-bound phones working; the desktop still confirms
    # every instruction before it becomes a normal chat message.
    "chat.instruct": "approve",
    "run.resume": "resume",
    "answer.select": "answer",
}

MAX_COMMAND_TTL_SECONDS = 60.0
MAX_CLOCK_SKEW_SECONDS = 30.0


class InMemoryReplayStore:
    """Nonce store used by tests and the local single-process M2 agent."""

    def __init__(self) -> None:
        self._seen: dict[str, datetime] = {}
        self._lock = threading.Lock()

    def _prune(self, now: datetime) -> None:
        expired = [
            nonce for nonce, expiry in self._seen.items()
            if expiry <= now
        ]
        for nonce in expired:
            self._seen.pop(nonce, None)

    def seen(self, nonce: str, now: datetime | None = None) -> bool:
        current = now or utc_now()
        with self._lock:
            self._prune(current)
            return nonce in self._seen

    def remember(self, nonce: str, expires_at: str) -> None:
        expiry = parse_timestamp(expires_at)
        with self._lock:
            self._seen[nonce] = expiry

    def clear(self) -> None:
        with self._lock:
            self._seen.clear()


def _deny(
    reason: str,
    *,
    risk: RiskLevel = "low",
    requires_local: bool = False,
) -> CommandDecision:
    return CommandDecision(
        allowed=False,
        reason=reason,
        risk=risk,
        requires_local=requires_local,
        status="requires_local" if requires_local else "denied",
    )


def validate_command(
    envelope: CommandEnvelope,
    *,
    device: DeviceInfo | None,
    verify_signature: Callable[[CommandEnvelope], bool] | None = None,
    approval: ApprovalRequest | None = None,
    replay_store: InMemoryReplayStore | None = None,
    now: datetime | None = None,
    allow_resume: bool = False,
) -> CommandDecision:
    """Validate one remote command against local policy.

    ``verify_signature`` is required.  M1 ships HMAC helpers for contract tests;
    M3 wires device public keys (P-256/Ed25519) into the same callback.
    """
    risk = INTENT_RISK.get(envelope.type)
    if envelope.v != 1:
        return _deny("unsupported command version")
    if risk is None:
        return _deny("unknown remote intent")
    if not envelope.command_id or not envelope.device_id or not envelope.nonce:
        return _deny("command_id, device_id and nonce are required")
    if not envelope.signature:
        return _deny("command is not signed")
    if device is None:
        return _deny("device is not bound")
    if device.device_id != envelope.device_id:
        return _deny("command device does not match the bound device")
    if device.is_revoked():
        return _deny("device has been revoked")
    if verify_signature is None:
        return _deny("signature verification is not configured")
    try:
        signature_ok = bool(verify_signature(envelope))
    except Exception:
        signature_ok = False
    if not signature_ok:
        return _deny("signature verification failed")

    permission = INTENT_PERMISSION.get(envelope.type, "")
    if not permission or not device.allows(permission):
        return _deny(f"device lacks the {permission or 'required'} permission")

    current = now or utc_now()
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    try:
        issued = parse_timestamp(envelope.issued_at)
        expires = parse_timestamp(envelope.expires_at)
    except ValueError:
        return _deny("issued_at and expires_at must be ISO-8601 timestamps")

    if issued > current.replace(microsecond=0) + timedelta(seconds=MAX_CLOCK_SKEW_SECONDS):
        return _deny("command was issued too far in the future")
    if expires <= current:
        return _deny("command has expired")
    ttl = (expires - issued).total_seconds()
    if ttl <= 0:
        return _deny("command expiry is before its issue time")
    if ttl > MAX_COMMAND_TTL_SECONDS:
        return _deny("command expiry exceeds the 60 second limit")

    if replay_store is not None and replay_store.seen(envelope.nonce, current):
        return _deny("command nonce has already been used")

    if envelope.type == "approval.decide":
        if approval is None:
            return _deny("approval.decide requires a matching approval request")
        if approval.action_hash != envelope.action_hash:
            return _deny("command is not bound to the displayed action hash")
        if not approval.is_remote_decidable(current):
            return _deny(
                "approval is expired, already decided, or high risk",
                risk=approval.risk,
                requires_local=approval.risk == "high",
            )
        risk = approval.risk
    elif envelope.type == "chat.instruct":
        text = (envelope.instruction or "").strip()
        if not text:
            return _deny("指令不能为空")
        if len(text) > MAX_INSTRUCTION_CHARS:
            return _deny(f"指令过长，最多 {MAX_INSTRUCTION_CHARS} 个字符")
    elif envelope.type == "run.resume" and not allow_resume:
        return _deny(
            "run.resume is disabled by local policy",
            risk=risk,
            requires_local=True,
        )

    if replay_store is not None:
        replay_store.remember(envelope.nonce, envelope.expires_at)

    return CommandDecision(
        allowed=True,
        reason="allowed",
        risk=risk,
        requires_local=False,
        status="allowed",
    )

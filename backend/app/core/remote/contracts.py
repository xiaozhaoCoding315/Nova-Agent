"""Wire contracts for the remote workbench.

Security invariants encoded here:

* A command is bound to one device, one intent and a short expiry.
* ``approval.decide`` is bound to the exact action hash the local agent showed.
* High-risk actions are never remotely approvable.
* Notifications carry summaries, never source code, secrets or full logs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

RiskLevel = Literal["low", "medium", "high"]
Intent = Literal[
    "status.get",
    "run.stop",
    "approval.list",
    "approval.decide",
    "run.resume",
    "answer.select",
]
CommandStatus = Literal["allowed", "denied", "requires_local"]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_timestamp(value: str) -> datetime:
    """Parse an ISO-8601 timestamp; naive values are treated as UTC."""
    raw = (value or "").strip()
    if not raw:
        raise ValueError("timestamp is empty")
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass
class ProgressEvent:
    """A redacted progress event safe to route through the relay."""

    event_id: str
    task_id: str
    session_id: str = ""
    kind: str = "progress"          # state | progress | message | approval | completed | failed
    status: str = ""                # queued | running | paused | needs_approval | completed | failed | stopped
    stage: str = ""
    percent: int | None = None
    summary: str = ""               # producer must redact before sending
    created_at: str = field(default_factory=lambda: utc_now().isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "task_id": self.task_id,
            "session_id": self.session_id,
            "kind": self.kind,
            "status": self.status,
            "stage": self.stage,
            "percent": self.percent,
            "summary": self.summary,
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ProgressEvent":
        data = data or {}
        return cls(
            event_id=str(data.get("event_id") or ""),
            task_id=str(data.get("task_id") or ""),
            session_id=str(data.get("session_id") or ""),
            kind=str(data.get("kind") or "progress"),
            status=str(data.get("status") or ""),
            stage=str(data.get("stage") or ""),
            percent=data.get("percent"),
            summary=str(data.get("summary") or ""),
            created_at=str(data.get("created_at") or utc_now().isoformat()),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass
class ApprovalRequest:
    """A pending local action, optionally exposed to a remote device."""

    approval_id: str
    task_id: str
    action_hash: str
    title: str = ""
    risk: RiskLevel = "medium"
    status: str = "pending"         # pending | approved | rejected | expired
    created_at: str = field(default_factory=lambda: utc_now().isoformat())
    expires_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_expired(self, now: datetime | None = None) -> bool:
        if not self.expires_at:
            return True
        return parse_timestamp(self.expires_at) <= (now or utc_now())

    def is_remote_decidable(self, now: datetime | None = None) -> bool:
        return (
            self.status == "pending"
            and self.risk != "high"
            and not self.is_expired(now)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "approval_id": self.approval_id,
            "task_id": self.task_id,
            "action_hash": self.action_hash,
            "title": self.title,
            "risk": self.risk,
            "status": self.status,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ApprovalRequest":
        data = data or {}
        return cls(
            approval_id=str(data.get("approval_id") or ""),
            task_id=str(data.get("task_id") or ""),
            action_hash=str(data.get("action_hash") or ""),
            title=str(data.get("title") or ""),
            risk=str(data.get("risk") or "medium"),  # type: ignore[arg-type]
            status=str(data.get("status") or "pending"),
            created_at=str(data.get("created_at") or utc_now().isoformat()),
            expires_at=str(data.get("expires_at") or ""),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass
class DeviceInfo:
    """A phone/workbench device known to the local agent."""

    device_id: str
    name: str = ""
    public_key: str = ""
    created_at: str = field(default_factory=lambda: utc_now().isoformat())
    revoked_at: str = ""
    permissions: list[str] = field(default_factory=lambda: ["status", "stop"])
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_revoked(self) -> bool:
        return bool(self.revoked_at)

    def allows(self, permission: str) -> bool:
        if self.is_revoked():
            return False
        return permission in self.permissions

    def to_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "name": self.name,
            "public_key": self.public_key,
            "created_at": self.created_at,
            "revoked_at": self.revoked_at,
            "permissions": list(self.permissions),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "DeviceInfo":
        data = data or {}
        return cls(
            device_id=str(data.get("device_id") or ""),
            name=str(data.get("name") or ""),
            public_key=str(data.get("public_key") or ""),
            created_at=str(data.get("created_at") or utc_now().isoformat()),
            revoked_at=str(data.get("revoked_at") or ""),
            permissions=list(data.get("permissions") or ["status", "stop"]),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass
class CommandEnvelope:
    """A signed, short-lived command from a bound device."""

    command_id: str
    device_id: str
    type: Intent
    nonce: str
    issued_at: str
    expires_at: str
    signature: str
    action_hash: str = ""
    args_ciphertext: str = ""
    v: int = 1

    def ttl_seconds(self) -> float:
        return (
            parse_timestamp(self.expires_at)
            - parse_timestamp(self.issued_at)
        ).total_seconds()

    def to_dict(self) -> dict[str, Any]:
        return {
            "v": self.v,
            "command_id": self.command_id,
            "device_id": self.device_id,
            "type": self.type,
            "action_hash": self.action_hash,
            "args_ciphertext": self.args_ciphertext,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "nonce": self.nonce,
            "signature": self.signature,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "CommandEnvelope":
        data = data or {}
        return cls(
            command_id=str(data.get("command_id") or ""),
            device_id=str(data.get("device_id") or ""),
            type=str(data.get("type") or ""),  # type: ignore[arg-type]
            nonce=str(data.get("nonce") or ""),
            issued_at=str(data.get("issued_at") or ""),
            expires_at=str(data.get("expires_at") or ""),
            signature=str(data.get("signature") or ""),
            action_hash=str(data.get("action_hash") or ""),
            args_ciphertext=str(data.get("args_ciphertext") or ""),
            v=int(data.get("v") or 1),
        )


@dataclass
class CommandDecision:
    """The local policy engine's verdict on a remote command."""

    allowed: bool
    reason: str
    risk: RiskLevel = "low"
    requires_local: bool = False
    status: CommandStatus = "denied"

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "risk": self.risk,
            "requires_local": self.requires_local,
            "status": self.status,
        }


@dataclass
class AuditEvent:
    """One auditable remote decision; no source code or secrets."""

    event_id: str
    device_id: str
    command_id: str
    type: str
    action_hash: str
    decision: str
    risk: RiskLevel
    created_at: str = field(default_factory=lambda: utc_now().isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "device_id": self.device_id,
            "command_id": self.command_id,
            "type": self.type,
            "action_hash": self.action_hash,
            "decision": self.decision,
            "risk": self.risk,
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
        }

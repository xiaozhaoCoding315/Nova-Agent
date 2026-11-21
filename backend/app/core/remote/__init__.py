"""Remote workbench contracts (M1).

This package defines the wire contract shared by the phone workbench, the
relay and the local agent.  M1 deliberately contains no network listener: the
local agent only opens an outbound connection in M2.  The contract is written
first so progress, approvals and stop commands cannot drift between surfaces.
"""
from app.core.remote.contracts import (
    ApprovalRequest,
    AuditEvent,
    CommandDecision,
    CommandEnvelope,
    DeviceInfo,
    ProgressEvent,
)
from app.core.remote.policy import (
    INTENT_RISK,
    InMemoryReplayStore,
    validate_command,
)

__all__ = [
    "ApprovalRequest",
    "AuditEvent",
    "CommandDecision",
    "CommandEnvelope",
    "DeviceInfo",
    "INTENT_RISK",
    "InMemoryReplayStore",
    "ProgressEvent",
    "validate_command",
]

"""Remote approval registry for local tool confirmations.

The phone can list and decide the same ``tool_approval`` the desktop shows.
Decisions are bound to the action hash, single-use and short-lived.  High-risk
tools are listed but never remotely decidable.
"""
from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from typing import Any

from app.core import approvals as local_approvals
from app.core.remote import store
from app.core.remote.contracts import utc_now
from app.core.remote.redact import redact_text
from app.core.security.risk import RiskLevel, grade_risk

# These tools can execute code/commands on the user's machine, install
# packages, run host diagnostics or send content to the network.  A phone may
# list them, but only the desktop can approve them.
_HIGH_TOOLS = {
    "run_command",
    "run_code",
    "local_run_command",
    "local_write_file",
    "install_deps",
    "diagnostics",
    "fetch_url",
    "web_search",
}
_APPROVAL_TTL_SECONDS = 300


def action_hash(tool_name: str, args: dict[str, Any]) -> str:
    payload = json.dumps(
        {"tool": tool_name, "args": args},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str,
    )
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def classify_risk(tool_name: str, args: dict[str, Any]) -> str:
    """Grade a pending tool call for remote approval.

    Anything that can execute code, install packages, run host diagnostics or
    send data to the network is high risk.  Unknown MCP tools and grading
    failures fail closed to high rather than becoming remotely approvable.
    """
    if tool_name in _HIGH_TOOLS or tool_name.startswith("mcp__"):
        return "high"
    try:
        payload = json.dumps(args, ensure_ascii=False, default=str)
        level, _ = grade_risk(payload)
    except Exception:
        return "high"
    if level == RiskLevel.BLOCK:
        return "high"
    if level == RiskLevel.WARN:
        return "medium"
    return "medium"


def register(
    *,
    user_id: int,
    session_id: str,
    task_id: str,
    tool_call_id: str,
    tool_name: str,
    args: dict[str, Any],
    reason: str = "",
    ttl_seconds: int = _APPROVAL_TTL_SECONDS,
) -> dict[str, Any] | None:
    """Record a pending approval only when a phone is actually bound."""
    if not store.has_active_devices(user_id):
        return None
    risk = classify_risk(tool_name, args)
    now = utc_now()
    record = {
        "approval_id": tool_call_id[:120],
        "session_id": session_id[:100],
        "task_id": task_id[:100],
        "tool_name": tool_name[:80],
        "title": f"{tool_name} 需要确认"[:200],
        "reason": redact_text(reason),
        "action_hash": action_hash(tool_name, args),
        "risk": risk,
        "remote_decidable": risk != "high",
        "status": "pending",
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(seconds=max(30, min(ttl_seconds, 600)))).isoformat(),
    }
    store.save_approval(user_id, record)
    return record


def decide(
    user_id: int, approval_id: str, expected_hash: str, approved: bool,
) -> dict[str, Any]:
    record = store.get_approval(user_id, approval_id)
    if not record:
        raise store.RemoteError("这条审批不存在或已失效")
    if record.get("status") != "pending":
        raise store.RemoteError("这条审批已经处理过了")
    if record.get("risk") == "high" or not record.get("remote_decidable"):
        raise store.RemoteError("高风险操作只能在电脑上确认")
    if not expected_hash or record.get("action_hash") != expected_hash:
        raise store.RemoteError("审批绑定的动作哈希不一致")
    try:
        from app.core.remote.contracts import parse_timestamp

        if parse_timestamp(str(record.get("expires_at") or "")) <= utc_now():
            raise store.RemoteError("这条审批已过期")
    except ValueError as exc:
        raise store.RemoteError("审批记录已损坏") from exc

    resolved = local_approvals.resolve(
        str(record.get("session_id") or ""),
        str(record.get("approval_id") or ""),
        user_id,
        approved,
    )
    if not resolved:
        raise store.RemoteError("审批已失效，请回到电脑上处理")
    status = "approved" if approved else "rejected"
    store.set_approval_status(user_id, approval_id, status)
    store.record_audit(user_id, {
        "action": "approval.decide",
        "approval_id": approval_id,
        "task_id": record.get("task_id", ""),
        "decision": status,
        "risk": record.get("risk", "medium"),
    })
    return {
        "approval_id": approval_id,
        "status": status,
        "action_hash": record.get("action_hash"),
    }


def record_local_decision(user_id: int, approval_id: str, approved: bool) -> None:
    """Keep the phone's approval list in sync with a desktop decision."""
    try:
        record = store.get_approval(user_id, approval_id)
        if not record or record.get("status") != "pending":
            return
        status = "approved" if approved else "rejected"
        store.set_approval_status(user_id, approval_id, status)
        store.record_audit(user_id, {
            "action": "approval.local_decide",
            "approval_id": approval_id,
            "task_id": record.get("task_id", ""),
            "decision": status,
            "risk": record.get("risk", "medium"),
        })
    except Exception:
        # A remote bookkeeping failure must never affect the local decision.
        return


def public_list(user_id: int) -> list[dict[str, Any]]:
    items = []
    for record in store.list_pending_approvals(user_id):
        items.append({
            "approval_id": record.get("approval_id", ""),
            "task_id": record.get("task_id", ""),
            "title": record.get("title", ""),
            "reason": record.get("reason", ""),
            "risk": record.get("risk", "medium"),
            "remote_decidable": bool(record.get("remote_decidable")),
            "action_hash": record.get("action_hash", ""),
            "expires_at": record.get("expires_at", ""),
        })
    return items


__all__ = [
    "action_hash", "classify_risk", "decide", "public_list", "record_local_decision",
    "register",
]

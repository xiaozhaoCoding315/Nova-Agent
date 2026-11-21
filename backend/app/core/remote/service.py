"""Remote command handling: signatures, policy, redacted progress and stop.

The remote workbench never gets a second execution path.  ``status.get`` reads
the existing turn records, ``run.stop`` uses the same cancel path as the
desktop, and every decision is written to both the local and relay audits.
"""
from __future__ import annotations

import contextlib
from typing import Any

from app.core.remote import approvals as remote_approvals
from app.core.remote import store
from app.core.remote.contracts import (
    ApprovalRequest,
    CommandDecision,
    CommandEnvelope,
    DeviceInfo,
    ProgressEvent,
    utc_now,
)
from app.core.remote.identity import verify_command_signature
from app.core.remote.policy import InMemoryReplayStore, validate_command
from app.core.remote.redact import redact_text
from app.core.turns import store as turn_store
from app.db import query

_replay_store = InMemoryReplayStore()


def replay_store() -> InMemoryReplayStore:
    return _replay_store


def _deny(
    reason: str, *, requires_local: bool = False, risk: str = "low",
) -> CommandDecision:
    return CommandDecision(
        allowed=False,
        reason=reason,
        risk=risk,  # type: ignore[arg-type]
        requires_local=requires_local,
        status="requires_local" if requires_local else "denied",
    )


def _device_info(device: store.Device) -> DeviceInfo:
    record = device.record
    return DeviceInfo(
        device_id=device.device_id,
        name=str(record.get("name") or ""),
        public_key="",
        created_at=str(record.get("created_at") or ""),
        revoked_at=str(record.get("revoked_at") or ""),
        permissions=device.permissions,
    )


def _audit(
    device: store.Device,
    envelope: CommandEnvelope,
    decision: CommandDecision,
) -> None:
    store.record_audit(device.user_id, {
        "action": "command",
        "device_id": device.device_id,
        "command_id": envelope.command_id,
        "type": envelope.type,
        "decision": decision.status,
        "reason": decision.reason,
        "risk": decision.risk,
    })
    store.relay_audit({
        "action": "command.route",
        "device_id": device.device_id,
        "command_id": envelope.command_id,
        "type": envelope.type,
        "decision": decision.status,
    })


def _summary_for_event(event_type: str, payload: dict[str, Any]) -> tuple[str, str, int | None]:
    """Return ``(kind, summary, percent)`` without exposing model output."""
    kind = "progress"
    stage = ""
    raw_stage = payload.get("stage") or payload.get("step")
    if isinstance(raw_stage, str):
        stage = redact_text(raw_stage, limit=40)
    percent = payload.get("percent")
    if not isinstance(percent, int) or isinstance(percent, bool):
        percent = None
    else:
        percent = max(0, min(percent, 100))

    if event_type == "token":
        return kind, "正在生成内容", percent
    if event_type == "tool_output":
        return kind, "正在执行工具", percent
    if event_type == "error":
        message = payload.get("message") or payload.get("detail") or "任务出错"
        return "failed", redact_text(message), percent
    if event_type in ("done", "complete", "completed"):
        return "completed", "任务已完成", 100
    message = payload.get("message") or payload.get("summary") or payload.get("text")
    summary = redact_text(message) if message else (f"阶段：{stage}" if stage else "任务进行中")
    return kind, summary, percent


async def build_progress(user_id: int) -> list[dict[str, Any]]:
    """Redacted progress for the user's active turns, newest first."""
    rows = await query(
        "SELECT id, session_id, status, created_at FROM turns "
        "WHERE user_id = %s AND status IN ('queued', 'running') "
        "ORDER BY created_at DESC LIMIT 5",
        (user_id,),
    )
    events: list[dict[str, Any]] = []
    for row in rows:
        turn_id = str(row[0])
        session_id = str(row[1])
        status = str(row[2])
        latest = await query(
            "SELECT type, payload FROM turn_events WHERE turn_id = %s "
            "ORDER BY seq DESC LIMIT 1",
            (turn_id,),
        )
        event_type = str(latest[0][0]) if latest else ""
        payload = latest[0][1] if latest and isinstance(latest[0][1], dict) else {}
        kind, summary, percent = _summary_for_event(event_type, payload)
        events.append(ProgressEvent(
            event_id=f"evt_{turn_id}",
            task_id=turn_id,
            session_id=session_id,
            kind=kind,
            status=status,
            stage=str(payload.get("stage") or "")[:40],
            percent=percent,
            summary=summary,
        ).to_dict())
    return events


async def stop_active_turns(user_id: int) -> list[str]:
    """Cancel every active turn for this user; safe to call repeatedly."""
    rows = await query(
        "SELECT id, job_id FROM turns "
        "WHERE user_id = %s AND status IN ('queued', 'running') "
        "ORDER BY created_at ASC",
        (user_id,),
    )
    stopped: list[str] = []
    for row in rows:
        turn_id = str(row[0])
        job_id = str(row[1]) if len(row) > 1 and row[1] else ""
        updated = await turn_store.request_cancel(turn_id)
        if updated is None:
            continue
        stopped.append(turn_id)
        if job_id:
            with contextlib.suppress(Exception):
                from app.core.jobs.runner import runner

                await runner.cancel(job_id, user_id)
    if stopped:
        store.add_notification(user_id, {
            "kind": "stopped",
            "status": "canceled",
            "summary": f"已停止 {len(stopped)} 个任务",
            "task_id": stopped[0],
        })
    return stopped


async def handle_command(payload: dict[str, Any]) -> dict[str, Any]:
    """Verify and execute one signed device command."""
    envelope = CommandEnvelope.from_dict(payload)
    if not envelope.device_id:
        raise store.RemoteError("命令缺少设备 ID")
    device = store.get_device(envelope.device_id)
    if device is None:
        store.relay_audit({
            "action": "command.route",
            "device_id": envelope.device_id[:80],
            "command_id": envelope.command_id[:80],
            "type": envelope.type[:40],
            "decision": "denied",
            "reason": "unknown_device",
        })
        raise store.RemoteError("设备未绑定")

    signature_ok = verify_command_signature(device.public_key, envelope)
    if device.status == "revoked" and signature_ok:
        denied = _deny("设备已撤销，请重新配对", requires_local=True)
        _audit(device, envelope, denied)
        return {"ok": False, "device_status": "revoked", "decision": denied.to_dict()}

    if envelope.type == "approval.decide" and signature_ok and device.status == "active":
        record = (
            store.get_approval(device.user_id, envelope.approval_id)
            if envelope.approval_id else None
        )
        if record is None:
            denied = _deny("这条审批不存在或已失效")
            _audit(device, envelope, denied)
            return {"ok": False, "device_status": "active", "decision": denied.to_dict()}
        if record.get("status") != "pending":
            denied = _deny("这条审批已经处理过了")
            _audit(device, envelope, denied)
            return {"ok": False, "device_status": "active", "decision": denied.to_dict()}
        if record.get("action_hash") != envelope.action_hash:
            denied = _deny("审批绑定的动作哈希不一致")
            _audit(device, envelope, denied)
            return {"ok": False, "device_status": "active", "decision": denied.to_dict()}
        if record.get("risk") == "high" or not record.get("remote_decidable"):
            denied = _deny("高风险操作只能在电脑上确认", requires_local=True, risk="high")
            _audit(device, envelope, denied)
            return {"ok": False, "device_status": "active", "decision": denied.to_dict()}

    approval_record = (
        store.get_approval(device.user_id, envelope.approval_id)
        if envelope.approval_id else None
    )
    approval_request = (
        ApprovalRequest(
            approval_id=str(approval_record.get("approval_id") or ""),
            task_id=str(approval_record.get("task_id") or ""),
            action_hash=str(approval_record.get("action_hash") or ""),
            title=str(approval_record.get("title") or ""),
            risk=str(approval_record.get("risk") or "medium"),  # type: ignore[arg-type]
            status=str(approval_record.get("status") or "pending"),
            created_at=str(approval_record.get("created_at") or ""),
            expires_at=str(approval_record.get("expires_at") or ""),
        )
        if approval_record else None
    )
    decision = validate_command(
        envelope,
        device=_device_info(device),
        verify_signature=lambda _envelope: signature_ok,
        approval=approval_request,
        replay_store=_replay_store,
        allow_resume=False,
    )
    if not decision.allowed:
        _audit(device, envelope, decision)
        return {
            "ok": False,
            "device_status": device.status,
            "decision": decision.to_dict(),
        }

    if device.status == "pending":
        if envelope.type != "status.get":
            denied = _deny("设备还没有在电脑上确认绑定", requires_local=True)
            _audit(device, envelope, denied)
            return {"ok": False, "device_status": "pending", "decision": denied.to_dict()}
        pairing = store.pairing_for_device(device.device_id) or {}
        _audit(device, envelope, decision)
        return {
            "ok": True,
            "device_status": "pending_confirmation",
            "decision": decision.to_dict(),
            "pairing": {
                "pair_id": pairing.get("pair_id", ""),
                "sas": pairing.get("sas", ""),
                "expires_at": pairing.get("expires_at", ""),
            },
        }

    if device.status != "active":
        denied = _deny("设备已撤销", requires_local=True)
        _audit(device, envelope, denied)
        return {"ok": False, "device_status": device.status, "decision": denied.to_dict()}

    store.touch_device(device.device_id)
    _audit(device, envelope, decision)

    if envelope.type == "status.get":
        return {
            "ok": True,
            "device_status": "active",
            "decision": decision.to_dict(),
            "server_time": utc_now().isoformat(),
            "events": await build_progress(device.user_id),
            "notifications": store.list_notifications(device.user_id, limit=20),
            "approvals": remote_approvals.public_list(device.user_id),
        }

    if envelope.type == "approval.list":
        return {
            "ok": True,
            "device_status": "active",
            "decision": decision.to_dict(),
            "approvals": remote_approvals.public_list(device.user_id),
        }

    if envelope.type == "approval.decide":
        approved = envelope.decision.lower() == "approve"
        if envelope.decision.lower() not in ("approve", "reject"):
            denied = _deny("审批决定必须是 approve 或 reject")
            _audit(device, envelope, denied)
            return {"ok": False, "device_status": "active", "decision": denied.to_dict()}
        try:
            result = remote_approvals.decide(
                device.user_id, envelope.approval_id, envelope.action_hash, approved,
            )
        except store.RemoteError as exc:
            denied = _deny(
                str(exc),
                requires_local="高风险" in str(exc),
                risk=approval_request.risk if approval_request else "medium",
            )
            _audit(device, envelope, denied)
            return {"ok": False, "device_status": "active", "decision": denied.to_dict()}
        return {
            "ok": True,
            "device_status": "active",
            "decision": decision.to_dict(),
            "approval": result,
        }

    if envelope.type == "run.stop":
        stopped = await stop_active_turns(device.user_id)
        return {
            "ok": True,
            "device_status": "active",
            "decision": decision.to_dict(),
            "stopped_task_ids": stopped,
            "idempotent": len(stopped) == 0,
        }

    denied = _deny(
        "这个操作需要在电脑上确认", requires_local=True, risk=decision.risk,
    )
    _audit(device, envelope, denied)
    return {"ok": False, "device_status": "active", "decision": denied.to_dict()}


def notify_turn_finished(user_id: int, turn_id: str, status: str) -> None:
    """Queue a redacted completion notification when a remote device is bound."""
    try:
        if not store.has_active_devices(user_id):
            return
        existing = store.list_notifications(user_id, limit=10)
        if any(
            item.get("task_id") == turn_id and item.get("status") == status
            for item in existing
        ):
            return
        label = {
            "succeeded": ("completed", "任务已完成"),
            "canceled": ("stopped", "任务已停止"),
            "failed": ("failed", "任务失败，详情请在电脑上查看"),
            "interrupted": ("failed", "任务被中断，详情请在电脑上查看"),
        }.get(status, ("status", "任务已结束"))
        store.add_notification(user_id, {
            "kind": label[0],
            "status": status,
            "summary": label[1],
            "task_id": turn_id,
        })
    except Exception:
        # Notifications must never affect local turn execution.
        return


__all__ = [
    "build_progress",
    "handle_command",
    "notify_turn_finished",
    "replay_store",
    "stop_active_turns",
]

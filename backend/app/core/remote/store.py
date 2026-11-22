"""Durable state for the remote workbench.

Layout under ``settings.user_data_dir``::

    remote/pairings/<pair_id>.json      一次性配对（含 token 哈希，不存明文）
    remote/devices/<device_id>.json     设备公钥与状态（pending/active/revoked）
    remote/users/<user_id>/audit.jsonl  本地审计（追加写）
    remote/users/<user_id>/notifications.json
    remote/relay-audit.jsonl            中继侧可见的最小路由元数据

No secrets are ever written in plaintext: pairing tokens are stored as
SHA-256 hashes, and the SAS is derived from a server-side pair secret.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from app.config import settings
from app.core.remote.contracts import MAX_INSTRUCTION_CHARS, parse_timestamp, utc_now
from app.core.remote.identity import (
    IdentityError,
    compute_sas,
    hash_token,
    new_token,
    normalize_public_key,
    token_matches,
)

PAIRING_TTL_SECONDS = 300
DEVICE_PERMISSIONS = ["status", "stop", "approve"]
_MAX_AUDIT_LINES = 500
_MAX_NOTIFICATIONS = 200
_MAX_INSTRUCTIONS = 100
_MAX_PENDING_INSTRUCTIONS = 5
_INSTRUCTION_TTL_HOURS = 24
_MAX_RELAY_AUDIT_LINES = 1000
_MAX_RELAY_AUDIT_BYTES = 2 * 1024 * 1024
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{4,80}$")

_lock = threading.RLock()


class RemoteError(Exception):
    """A remote-workbench operation was refused."""


def _root() -> Path:
    return Path(settings.user_data_dir) / "remote"


def _safe_id(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not _ID_RE.fullmatch(text):
        raise RemoteError(f"{label}格式不正确")
    return text


def _user_segment(user_id: int | str) -> str:
    text = str(user_id).strip()
    if not text.isdigit():
        raise RemoteError("用户 ID 格式不正确")
    return text


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _write_json(path: Path, value: dict[str, Any] | list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)
    try:
        temporary.write_text(data, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink(missing_ok=True)


def _parse(value: str) -> datetime:
    raw = (value or "").strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=utc_now().tzinfo)
    return parsed


def _expired(record: dict[str, Any], now: datetime | None = None) -> bool:
    try:
        return _parse(str(record.get("expires_at") or "")) <= (now or utc_now())
    except ValueError:
        return True


def _public_device(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "device_id": record.get("device_id", ""),
        "name": record.get("name", ""),
        "status": record.get("status", "pending"),
        "created_at": record.get("created_at", ""),
        "confirmed_at": record.get("confirmed_at", ""),
        "revoked_at": record.get("revoked_at", ""),
        "last_seen_at": record.get("last_seen_at", ""),
        "permissions": list(record.get("permissions") or []),
        "public_key": dict(record.get("public_key") or {}),
    }


def _public_pairing(record: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    status = str(record.get("status") or "pending")
    if status in ("pending", "claimed") and _expired(record, now):
        status = "expired"
    return {
        "pair_id": record.get("pair_id", ""),
        "status": status,
        "created_at": record.get("created_at", ""),
        "expires_at": record.get("expires_at", ""),
        "claimed_at": record.get("claimed_at", ""),
        "confirmed_at": record.get("confirmed_at", ""),
        "device_id": record.get("device_id", ""),
        "device_name": record.get("device_name", ""),
        "sas": record.get("sas", ""),
    }


@dataclass
class PairingHandle:
    pairing: dict[str, Any]
    token: str


@dataclass
class Device:
    record: dict[str, Any] = field(default_factory=dict)

    @property
    def device_id(self) -> str:
        return str(self.record.get("device_id") or "")

    @property
    def user_id(self) -> int:
        return int(self.record.get("user_id") or 0)

    @property
    def status(self) -> str:
        return str(self.record.get("status") or "pending")

    @property
    def public_key(self) -> dict[str, str]:
        return dict(self.record.get("public_key") or {})

    @property
    def permissions(self) -> list[str]:
        return list(self.record.get("permissions") or [])

    def to_public_dict(self) -> dict[str, Any]:
        return _public_device(self.record)


def create_pairing(
    user_id: int | str, *, ttl_seconds: int = PAIRING_TTL_SECONDS,
) -> PairingHandle:
    owner = _user_segment(user_id)
    pair_id = f"pair_{secrets.token_hex(8)}"
    token = new_token(32)
    now = utc_now()
    record = {
        "pair_id": pair_id,
        "user_id": int(owner),
        "token_hash": hash_token(token),
        "secret": secrets.token_hex(32),
        "status": "pending",
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(seconds=max(60, min(ttl_seconds, 900)))).isoformat(),
        "claimed_at": "",
        "confirmed_at": "",
        "device_id": "",
        "device_name": "",
        "sas": "",
        "failures": 0,
    }
    with _lock:
        _write_json(_root() / "pairings" / f"{pair_id}.json", record)
    _record_audit(
        int(owner), {
            "action": "pairing.create",
            "pair_id": pair_id,
            "decision": "allowed",
            "risk": "low",
        },
    )
    return PairingHandle(pairing=_public_pairing(record), token=token)


def load_pairing(pair_id: str, *, user_id: int | str | None = None) -> dict[str, Any]:
    safe = _safe_id(pair_id, "配对 ID")
    record = _read_json(_root() / "pairings" / f"{safe}.json")
    if not record:
        raise RemoteError("配对不存在")
    if user_id is not None and str(record.get("user_id")) != _user_segment(user_id):
        raise RemoteError("配对不存在")
    return record


def get_pairing(pair_id: str, *, user_id: int | str | None = None) -> dict[str, Any]:
    return _public_pairing(load_pairing(pair_id, user_id=user_id))


def claim_pairing(
    pair_id: str,
    token: str,
    *,
    device_name: str,
    public_key: Any,
    encryption_public_key: Any = None,
) -> dict[str, Any]:
    """Bind a phone key to a pending pairing.  The token is single-use."""
    safe = _safe_id(pair_id, "配对 ID")
    with _lock:
        record = load_pairing(safe)
        if _expired(record):
            raise RemoteError("配对链接已过期，请在电脑上重新生成")
        if record.get("status") != "pending":
            raise RemoteError("配对链接已被使用")
        if not token_matches(token, str(record.get("token_hash") or "")):
            raise RemoteError("配对链接无效")
        try:
            key = normalize_public_key(public_key)
            encryption = (
                normalize_public_key(encryption_public_key)
                if encryption_public_key else {}
            )
        except IdentityError as exc:
            raise RemoteError(str(exc)) from exc
        try:
            secret = bytes.fromhex(str(record.get("secret") or ""))
        except ValueError as exc:
            raise RemoteError("配对密钥已损坏，请重新生成") from exc
        if len(secret) < 16:
            raise RemoteError("配对密钥已损坏，请重新生成")

        now = utc_now()
        sas = compute_sas(secret, key)
        device_id = f"dev_{secrets.token_hex(8)}"
        device = {
            "device_id": device_id,
            "user_id": int(record["user_id"]),
            "name": (device_name or "手机").strip()[:60] or "手机",
            "public_key": key,
            "encryption_public_key": encryption,
            "status": "pending",
            "permissions": list(DEVICE_PERMISSIONS),
            "created_at": now.isoformat(),
            "confirmed_at": "",
            "revoked_at": "",
            "last_seen_at": "",
        }
        record.update({
            "status": "claimed",
            "device_id": device_id,
            "device_name": device["name"],
            "sas": sas,
            "claimed_at": now.isoformat(),
        })
        _write_json(_root() / "devices" / f"{device_id}.json", device)
        _write_json(_root() / "pairings" / f"{safe}.json", record)
    _relay_audit({
        "action": "pairing.claim",
        "pair_id": safe,
        "device_id": device_id,
        "decision": "pending_confirmation",
    })
    return {
        "pair_id": safe,
        "device_id": device_id,
        "device_name": device["name"],
        "sas": sas,
        "status": "pending_confirmation",
        "expires_at": record["expires_at"],
        "permissions": list(DEVICE_PERMISSIONS),
    }


def confirm_pairing(
    pair_id: str, user_id: int | str, sas: str,
) -> dict[str, Any]:
    safe = _safe_id(pair_id, "配对 ID")
    owner = _user_segment(user_id)
    with _lock:
        record = load_pairing(safe, user_id=owner)
        if record.get("status") == "confirmed":
            raise RemoteError("这个配对已经确认过了")
        if record.get("status") != "claimed":
            raise RemoteError("手机还没有提交配对请求")
        if _expired(record):
            raise RemoteError("配对已过期，请在电脑上重新生成")
        expected = str(record.get("sas") or "")
        if not expected or not secrets.compare_digest(
            expected.replace(" ", ""), (sas or "").replace(" ", ""),
        ):
            failures = int(record.get("failures") or 0) + 1
            record["failures"] = failures
            if failures >= 5:
                record["status"] = "rejected"
                device = _read_json(_root() / "devices" / f"{record.get('device_id', '')}.json")
                if device:
                    device["status"] = "revoked"
                    device["revoked_at"] = utc_now().isoformat()
                    _write_json(_root() / "devices" / f"{device['device_id']}.json", device)
            _write_json(_root() / "pairings" / f"{safe}.json", record)
            _record_audit(int(owner), {
                "action": "pairing.confirm", "pair_id": safe,
                "decision": "denied", "reason": "SAS 不匹配", "risk": "high",
            })
            raise RemoteError("验证串不一致，请重新核对手机和电脑上的数字")

        device_id = _safe_id(record.get("device_id"), "设备 ID")
        device = _read_json(_root() / "devices" / f"{device_id}.json")
        if not device or device.get("status") == "revoked":
            raise RemoteError("设备已失效，请重新配对")
        now = utc_now().isoformat()
        device["status"] = "active"
        device["confirmed_at"] = now
        record["status"] = "confirmed"
        record["confirmed_at"] = now
        _write_json(_root() / "devices" / f"{device_id}.json", device)
        _write_json(_root() / "pairings" / f"{safe}.json", record)
    add_notification(int(owner), {
        "kind": "device",
        "status": "confirmed",
        "summary": f"设备「{device.get('name') or '手机'}」已绑定，可查看进度并停止任务",
        "task_id": "",
        "device_id": device_id,
    })
    _record_audit(int(owner), {
        "action": "pairing.confirm", "pair_id": safe, "device_id": device_id,
        "decision": "allowed", "risk": "medium",
    })
    return _public_device(device)


def reject_pairing(pair_id: str, user_id: int | str) -> dict[str, Any]:
    safe = _safe_id(pair_id, "配对 ID")
    owner = _user_segment(user_id)
    with _lock:
        record = load_pairing(safe, user_id=owner)
        record["status"] = "rejected"
        _write_json(_root() / "pairings" / f"{safe}.json", record)
        device_id = str(record.get("device_id") or "")
        if device_id:
            try:
                device = _read_json(_root() / "devices" / f"{_safe_id(device_id, '设备 ID')}.json")
            except RemoteError:
                device = None
            if device and device.get("status") != "revoked":
                device["status"] = "revoked"
                device["revoked_at"] = utc_now().isoformat()
                _write_json(_root() / "devices" / f"{device_id}.json", device)
    _record_audit(int(owner), {
        "action": "pairing.reject", "pair_id": safe, "device_id": device_id,
        "decision": "allowed", "risk": "low",
    })
    return {"ok": True, "pair_id": safe, "status": "rejected"}


def get_device(device_id: str, *, user_id: int | str | None = None) -> Device | None:
    try:
        safe = _safe_id(device_id, "设备 ID")
    except RemoteError:
        return None
    record = _read_json(_root() / "devices" / f"{safe}.json")
    if not record:
        return None
    if user_id is not None and str(record.get("user_id")) != _user_segment(user_id):
        return None
    return Device(record=record)


def pairing_for_device(device_id: str) -> dict[str, Any] | None:
    """Return the pairing that produced a device, without its secrets."""
    try:
        safe = _safe_id(device_id, "设备 ID")
    except RemoteError:
        return None
    root = _root() / "pairings"
    if not root.is_dir():
        return None
    for path in root.glob("*.json"):
        record = _read_json(path)
        if record and str(record.get("device_id") or "") == safe:
            return _public_pairing(record)
    return None


def list_devices(user_id: int | str) -> list[dict[str, Any]]:
    owner = _user_segment(user_id)
    root = _root() / "devices"
    if not root.is_dir():
        return []
    items: list[dict[str, Any]] = []
    for path in root.glob("*.json"):
        record = _read_json(path)
        if record and str(record.get("user_id")) == owner:
            items.append(_public_device(record))
    return sorted(items, key=lambda item: item.get("created_at", ""), reverse=True)


def touch_device(device_id: str) -> None:
    try:
        safe = _safe_id(device_id, "设备 ID")
    except RemoteError:
        return
    path = _root() / "devices" / f"{safe}.json"
    with _lock:
        record = _read_json(path)
        if record:
            record["last_seen_at"] = utc_now().isoformat()
            _write_json(path, record)


def revoke_device(device_id: str, user_id: int | str) -> dict[str, Any]:
    safe = _safe_id(device_id, "设备 ID")
    owner = _user_segment(user_id)
    with _lock:
        device = get_device(safe, user_id=owner)
        if not device:
            raise RemoteError("设备不存在")
        if device.status == "revoked":
            return device.to_public_dict()
        record = device.record
        record["status"] = "revoked"
        record["revoked_at"] = utc_now().isoformat()
        _write_json(_root() / "devices" / f"{safe}.json", record)
    add_notification(int(owner), {
        "kind": "device",
        "status": "revoked",
        "summary": f"设备「{record.get('name') or '手机'}」已撤销，旧命令立即失效",
        "task_id": "",
        "device_id": safe,
    })
    _record_audit(int(owner), {
        "action": "device.revoke", "device_id": safe,
        "decision": "allowed", "risk": "medium",
    })
    return _public_device(record)


def has_active_devices(user_id: int | str) -> bool:
    return any(
        item.get("status") == "active" for item in list_devices(user_id)
    )


def add_notification(user_id: int | str, notification: dict[str, Any]) -> dict[str, Any]:
    """Append one redacted notification.  Callers must not pass raw code/secrets."""
    owner = _user_segment(user_id)
    now = utc_now().isoformat()
    item = {
        "id": f"ntf_{secrets.token_hex(8)}",
        "kind": str(notification.get("kind") or "status")[:20],
        "status": str(notification.get("status") or "")[:20],
        "summary": str(notification.get("summary") or "")[:200],
        "task_id": str(notification.get("task_id") or "")[:100],
        "device_id": str(notification.get("device_id") or "")[:80],
        "created_at": now,
        "read": False,
    }
    path = _root() / "users" / owner / "notifications.json"
    with _lock:
        existing = _read_json(path)
        items = existing.get("items") if isinstance(existing, dict) else []
        items = items if isinstance(items, list) else []
        items = [item] + [entry for entry in items if isinstance(entry, dict)]
        _write_json(path, {"items": items[:_MAX_NOTIFICATIONS]})
    return item


def list_notifications(
    user_id: int | str, *, limit: int = 50, unread_only: bool = False,
) -> list[dict[str, Any]]:
    owner = _user_segment(user_id)
    payload = _read_json(_root() / "users" / owner / "notifications.json") or {}
    items = payload.get("items") if isinstance(payload, dict) else []
    items = [entry for entry in (items or []) if isinstance(entry, dict)]
    if unread_only:
        items = [entry for entry in items if not entry.get("read")]
    return items[: max(1, min(int(limit), 200))]


def mark_notifications_read(
    user_id: int | str, ids: list[str] | None = None,
) -> int:
    owner = _user_segment(user_id)
    path = _root() / "users" / owner / "notifications.json"
    wanted = {str(value) for value in (ids or [])}
    with _lock:
        payload = _read_json(path) or {}
        items = payload.get("items") if isinstance(payload, dict) else []
        changed = 0
        for entry in items or []:
            if not isinstance(entry, dict) or entry.get("read"):
                continue
            if wanted and str(entry.get("id")) not in wanted:
                continue
            entry["read"] = True
            changed += 1
        _write_json(path, {"items": items or []})
    return changed


def _instructions_path(user_id: int | str) -> Path:
    return _root() / "users" / _user_segment(user_id) / "instructions.json"


def _clean_instruction(text: Any) -> str:
    """Normalize phone input and drop control characters before storing."""
    value = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    value = "".join(
        ch for ch in value
        if ch in ("\n", "\t") or ord(ch) >= 32
    )
    return value.strip()


def _prune_instructions(items: list[dict[str, Any]]) -> bool:
    """Mark pending instructions past their TTL as expired; return if changed."""
    now = utc_now()
    changed = False
    for item in items:
        if item.get("status") != "pending":
            continue
        try:
            expired = parse_timestamp(str(item.get("expires_at") or "")) <= now
        except ValueError:
            expired = True
        if expired:
            item["status"] = "expired"
            item["resolved_at"] = now.isoformat()
            changed = True
    return changed


def add_instruction(
    user_id: int | str, *, device_id: str, text: Any,
) -> dict[str, Any]:
    """Queue one phone instruction for local confirmation (never executed here)."""
    cleaned = _clean_instruction(text)
    if not cleaned:
        raise RemoteError("指令不能为空")
    if len(cleaned) > MAX_INSTRUCTION_CHARS:
        raise RemoteError(f"指令过长，最多 {MAX_INSTRUCTION_CHARS} 个字符")
    safe_device = _safe_id(device_id, "设备 ID")
    path = _instructions_path(user_id)
    now = utc_now()
    item = {
        "instruction_id": f"ins_{secrets.token_hex(8)}",
        "device_id": safe_device,
        "text": cleaned,
        "status": "pending",
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=_INSTRUCTION_TTL_HOURS)).isoformat(),
        "resolved_at": "",
    }
    with _lock:
        payload = _read_json(path) or {}
        items = payload.get("items") if isinstance(payload, dict) else []
        items = [entry for entry in (items or []) if isinstance(entry, dict)]
        _prune_instructions(items)
        pending = sum(1 for entry in items if entry.get("status") == "pending")
        if pending >= _MAX_PENDING_INSTRUCTIONS:
            _write_json(path, {"items": items})
            raise RemoteError("等待电脑确认的指令太多，请先在电脑上处理")
        items = [item] + items
        _write_json(path, {"items": items[:_MAX_INSTRUCTIONS]})
    return item


def list_instructions(
    user_id: int | str, *, status: str | None = None, limit: int = 20,
) -> list[dict[str, Any]]:
    path = _instructions_path(user_id)
    with _lock:
        payload = _read_json(path) or {}
        items = payload.get("items") if isinstance(payload, dict) else []
        items = [entry for entry in (items or []) if isinstance(entry, dict)]
        # Prune and persist under the same lock as add/resolve, otherwise a
        # concurrent poll could write back a stale snapshot and erase a new
        # instruction (or resurrect one that was just resolved).
        if _prune_instructions(items):
            _write_json(path, {"items": items[:_MAX_INSTRUCTIONS]})
    if status:
        items = [entry for entry in items if entry.get("status") == status]
    return items[: max(1, min(int(limit), 100))]


def resolve_instruction(
    user_id: int | str, instruction_id: str, status: str,
) -> dict[str, Any]:
    """Mark one instruction as sent into the chat or rejected by the desktop."""
    if status not in ("sent", "rejected"):
        raise RemoteError("指令只能标记为 sent 或 rejected")
    safe = _safe_id(instruction_id, "指令 ID")
    path = _instructions_path(user_id)
    with _lock:
        payload = _read_json(path) or {}
        items = payload.get("items") if isinstance(payload, dict) else []
        items = [entry for entry in (items or []) if isinstance(entry, dict)]
        _prune_instructions(items)
        target = next(
            (entry for entry in items if entry.get("instruction_id") == safe), None,
        )
        if target is None:
            _write_json(path, {"items": items[:_MAX_INSTRUCTIONS]})
            raise RemoteError("这条指令不存在")
        if target.get("status") != "pending":
            _write_json(path, {"items": items[:_MAX_INSTRUCTIONS]})
            raise RemoteError("这条指令已经处理过了")
        target["status"] = status
        target["resolved_at"] = utc_now().isoformat()
        _write_json(path, {"items": items[:_MAX_INSTRUCTIONS]})
    return target


def mark_notifications_for_task(user_id: int | str, task_id: str) -> int:
    """Mark the instruction notification read once the desktop handles it."""
    owner = _user_segment(user_id)
    path = _root() / "users" / owner / "notifications.json"
    changed = 0
    with _lock:
        payload = _read_json(path) or {}
        items = payload.get("items") if isinstance(payload, dict) else []
        for entry in items or []:
            if not isinstance(entry, dict) or entry.get("read"):
                continue
            if str(entry.get("task_id") or "") != task_id:
                continue
            entry["read"] = True
            changed += 1
        _write_json(path, {"items": items or []})
    return changed


def _approvals_path(user_id: int | str) -> Path:
    return _root() / "users" / _user_segment(user_id) / "approvals.json"


def save_approval(user_id: int | str, approval: dict[str, Any]) -> None:
    """Remember a pending local approval so a phone can list/decide it."""
    owner = _user_segment(user_id)
    path = _approvals_path(owner)
    with _lock:
        payload = _read_json(path) or {}
        items = payload.get("items") if isinstance(payload, dict) else []
        items = [item for item in (items or []) if isinstance(item, dict)]
        items = [item for item in items if item.get("approval_id") != approval.get("approval_id")]
        items.insert(0, dict(approval))
        _write_json(path, {"items": items[:50]})


def list_pending_approvals(user_id: int | str) -> list[dict[str, Any]]:
    owner = _user_segment(user_id)
    payload = _read_json(_approvals_path(owner)) or {}
    items = payload.get("items") if isinstance(payload, dict) else []
    now = utc_now()
    pending: list[dict[str, Any]] = []
    for item in items or []:
        if not isinstance(item, dict) or item.get("status") != "pending":
            continue
        try:
            expired = _parse(str(item.get("expires_at") or "")) <= now
        except ValueError:
            expired = True
        if expired:
            continue
        pending.append(item)
    return pending


def get_approval(user_id: int | str, approval_id: str) -> dict[str, Any] | None:
    owner = _user_segment(user_id)
    safe = str(approval_id or "")[:120]
    payload = _read_json(_approvals_path(owner)) or {}
    items = payload.get("items") if isinstance(payload, dict) else []
    for item in items or []:
        if isinstance(item, dict) and item.get("approval_id") == safe:
            return item
    return None


def set_approval_status(
    user_id: int | str, approval_id: str, status: str,
) -> bool:
    owner = _user_segment(user_id)
    path = _approvals_path(owner)
    safe = str(approval_id or "")[:120]
    with _lock:
        payload = _read_json(path) or {}
        items = payload.get("items") if isinstance(payload, dict) else []
        changed = False
        for item in items or []:
            if isinstance(item, dict) and item.get("approval_id") == safe:
                item["status"] = status
                item["decided_at"] = utc_now().isoformat()
                changed = True
                break
        if changed:
            _write_json(path, {"items": items or []})
    return changed


def _record_audit(user_id: int | str, event: dict[str, Any]) -> None:
    owner = _user_segment(user_id)
    entry = {
        "event_id": f"aud_{secrets.token_hex(8)}",
        "user_id": int(owner),
        "created_at": utc_now().isoformat(),
        **{key: value for key, value in event.items() if key != "user_id"},
    }
    path = _root() / "users" / owner / "audit.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        try:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
            lines = path.read_text(encoding="utf-8").splitlines()
            if len(lines) > _MAX_AUDIT_LINES:
                path.write_text("\n".join(lines[-_MAX_AUDIT_LINES:]) + "\n", encoding="utf-8")
        except OSError:
            return


def record_audit(user_id: int | str, event: dict[str, Any]) -> None:
    """Public local audit writer used by the command handler."""
    _record_audit(user_id, event)


def list_audit(user_id: int | str, *, limit: int = 100) -> list[dict[str, Any]]:
    owner = _user_segment(user_id)
    path = _root() / "users" / owner / "audit.jsonl"
    if not path.is_file():
        return []
    items: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines()[-max(1, min(limit, 500)):]:
            try:
                value = json.loads(line)
            except ValueError:
                continue
            if isinstance(value, dict):
                items.append(value)
    except OSError:
        return []
    return list(reversed(items))


def _relay_audit(event: dict[str, Any]) -> None:
    """The relay only ever sees routing metadata, never summaries or keys."""
    entry = {
        "event_id": f"relay_{secrets.token_hex(8)}",
        "created_at": utc_now().isoformat(),
        **event,
    }
    path = _root() / "relay-audit.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with _lock:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
            if path.stat().st_size > _MAX_RELAY_AUDIT_BYTES:
                lines = path.read_text(encoding="utf-8").splitlines()
                path.write_text(
                    "\n".join(lines[-_MAX_RELAY_AUDIT_LINES:]) + "\n",
                    encoding="utf-8",
                )
    except OSError:
        return


def relay_audit(event: dict[str, Any]) -> None:
    _relay_audit(event)


def list_relay_audit(*, limit: int = 100) -> list[dict[str, Any]]:
    """Read only the tail of the relay audit; the file can grow large."""
    path = _root() / "relay-audit.jsonl"
    if not path.is_file():
        return []
    items: list[dict[str, Any]] = []
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            start = max(0, size - 512 * 1024)
            handle.seek(start)
            data = handle.read()
    except OSError:
        return []
    lines = data.decode("utf-8", "replace").splitlines()
    if start > 0 and lines:
        lines = lines[1:]  # drop a possibly truncated first line
    for line in lines[-max(1, min(limit, 500)):]:
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            items.append(value)
    return list(reversed(items))


__all__ = [
    "DEVICE_PERMISSIONS",
    "Device",
    "PAIRING_TTL_SECONDS",
    "PairingHandle",
    "RemoteError",
    "add_notification",
    "claim_pairing",
    "confirm_pairing",
    "create_pairing",
    "get_approval",
    "get_device",
    "get_pairing",
    "has_active_devices",
    "list_audit",
    "list_devices",
    "list_notifications",
    "list_pending_approvals",
    "list_relay_audit",
    "load_pairing",
    "mark_notifications_read",
    "pairing_for_device",
    "record_audit",
    "reject_pairing",
    "relay_audit",
    "revoke_device",
    "save_approval",
    "set_approval_status",
    "touch_device",
]

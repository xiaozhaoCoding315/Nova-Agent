"""Remote workbench API: pairing, signed commands, progress, stop and audit.

There is no new network listener and no public local port.  In direct mode the
phone talks to the same HTTPS origin as the desktop; when a controlled relay is
configured, only signed envelopes and routing metadata cross it.
"""
from __future__ import annotations

import json
import threading
import time
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.config import settings
from app.core.remote import store
from app.core.remote.service import handle_command
from app.core.security.auth import get_current_user

router = APIRouter()

_CLAIM_WINDOW_SECONDS = 60.0
_CLAIM_LIMIT = 12
_claim_lock = threading.Lock()
_claim_times: dict[str, list[float]] = {}


class PairingCreateIn(BaseModel):
    ttl_seconds: int = Field(default=300, ge=60, le=900)


class PairingClaimIn(BaseModel):
    pair_id: str = Field(min_length=4, max_length=80)
    token: str = Field(min_length=20, max_length=200)
    device_name: str = Field(default="手机", max_length=60)
    public_key: dict[str, Any]
    encryption_public_key: dict[str, Any] | None = None


class PairingConfirmIn(BaseModel):
    sas: str = Field(min_length=4, max_length=20)


class NotificationsReadIn(BaseModel):
    ids: list[str] = Field(default_factory=list, max_length=100)


def _enabled() -> None:
    if not settings.remote_enabled:
        raise HTTPException(status_code=404, detail="远程工作台未开启")


def _rate_limit(host: str) -> None:
    now = time.monotonic()
    key = host or "unknown"
    with _claim_lock:
        values = [value for value in _claim_times.get(key, []) if now - value < _CLAIM_WINDOW_SECONDS]
        if len(values) >= _CLAIM_LIMIT:
            raise HTTPException(status_code=429, detail="配对尝试过于频繁，请稍后再试")
        values.append(now)
        _claim_times[key] = values


def _base_url(request: Request) -> str:
    return (settings.remote_public_url or str(request.base_url)).rstrip("/")


@router.get("/remote/config")
async def remote_config(user: dict = Depends(get_current_user)):
    _enabled()
    return {
        "enabled": True,
        "mode": "relay" if settings.remote_relay_url.strip() else "direct",
        "pairing_ttl_seconds": settings.remote_pairing_ttl_seconds,
        "workbench_path": "/m",
        "commands": ["status.get", "run.stop", "approval.list", "approval.decide"],
        "transport": "same-origin HTTPS; 本地不新开公网端口",
    }


@router.post("/remote/pairings")
async def create_pairing(
    request: Request,
    body: PairingCreateIn | None = None,
    user: dict = Depends(get_current_user),
):
    _enabled()
    ttl = (body.ttl_seconds if body else settings.remote_pairing_ttl_seconds)
    handle = store.create_pairing(user["id"], ttl_seconds=ttl)
    pairing = handle.pairing
    link = (
        f"{_base_url(request)}/m#pair_id={pairing['pair_id']}"
        f"&token={handle.token}"
    )
    return {
        "pairing": pairing,
        "token": handle.token,
        "link": link,
        "expires_at": pairing["expires_at"],
        "ttl_seconds": ttl,
        "note": "token 只显示这一次；链接里的秘密放在 # 后，不进入服务器查询日志。",
    }


@router.get("/remote/pairings/{pair_id}")
async def get_pairing(
    pair_id: str,
    user: dict = Depends(get_current_user),
):
    _enabled()
    try:
        pairing = store.get_pairing(pair_id, user_id=user["id"])
    except store.RemoteError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    device = None
    if pairing.get("device_id"):
        found = store.get_device(str(pairing["device_id"]), user_id=user["id"])
        device = found.to_public_dict() if found else None
    return {"pairing": pairing, "device": device}


@router.post("/remote/pair/claim")
async def claim_pairing(
    body: PairingClaimIn,
    request: Request,
):
    """Public endpoint used by the phone; the one-time token is the proof."""
    _enabled()
    host = request.client.host if request.client else "unknown"
    _rate_limit(host)
    try:
        result = store.claim_pairing(
            body.pair_id,
            body.token,
            device_name=body.device_name,
            public_key=body.public_key,
            encryption_public_key=body.encryption_public_key,
        )
    except store.RemoteError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result


@router.post("/remote/pairings/{pair_id}/confirm")
async def confirm_pairing(
    pair_id: str,
    body: PairingConfirmIn,
    user: dict = Depends(get_current_user),
):
    _enabled()
    try:
        device = store.confirm_pairing(pair_id, user["id"], body.sas)
    except store.RemoteError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "device": device}


@router.post("/remote/pairings/{pair_id}/reject")
async def reject_pairing(
    pair_id: str,
    user: dict = Depends(get_current_user),
):
    _enabled()
    try:
        return store.reject_pairing(pair_id, user["id"])
    except store.RemoteError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/remote/commands")
async def run_command(payload: dict[str, Any] = Body(...)):
    """Verify and run one signed command from a bound device."""
    _enabled()
    if len(json.dumps(payload, ensure_ascii=False, default=str)) > 20_000:
        raise HTTPException(status_code=413, detail="命令内容过大")
    try:
        return await handle_command(payload)
    except store.RemoteError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/remote/devices")
async def list_devices(user: dict = Depends(get_current_user)):
    _enabled()
    return {"devices": store.list_devices(user["id"])}


@router.post("/remote/devices/{device_id}/revoke")
async def revoke_device(
    device_id: str,
    user: dict = Depends(get_current_user),
):
    _enabled()
    try:
        return {"ok": True, "device": store.revoke_device(device_id, user["id"])}
    except store.RemoteError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/remote/notifications")
async def list_notifications(
    unread_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    user: dict = Depends(get_current_user),
):
    _enabled()
    items = store.list_notifications(user["id"], limit=limit, unread_only=unread_only)
    return {
        "notifications": items,
        "unread": len(store.list_notifications(user["id"], limit=200, unread_only=True)),
    }


@router.post("/remote/notifications/read")
async def read_notifications(
    body: NotificationsReadIn,
    user: dict = Depends(get_current_user),
):
    _enabled()
    changed = store.mark_notifications_read(user["id"], body.ids)
    return {"ok": True, "changed": changed}


@router.get("/remote/audit")
async def remote_audit(
    limit: int = Query(default=100, ge=1, le=500),
    user: dict = Depends(get_current_user),
):
    _enabled()
    device_ids = {item["device_id"] for item in store.list_devices(user["id"])}
    relay = [
        item for item in store.list_relay_audit(limit=500)
        if str(item.get("device_id") or "") in device_ids
    ][:limit]
    return {
        "local": store.list_audit(user["id"], limit=limit),
        "relay": relay,
        "note": "本地审计含决定与风险级别；中继审计只有路由元数据。",
    }


__all__ = ["router"]

"""Night queue endpoints: queue changes / bug tasks for unattended night runs."""
from fastapi import APIRouter, Depends, HTTPException

from app.core.night.service import cancel_item, enqueue_item, list_items
from app.core.security.audit import log_audit
from app.core.security.auth import get_current_user
from app.models.schemas import NightItemOut, NightQueueRequest

router = APIRouter()


@router.get("/night-queue", response_model=list[NightItemOut])
async def list_night_queue(user: dict = Depends(get_current_user)):
    return await list_items(user["id"])


@router.post("/night-queue", response_model=NightItemOut)
async def add_night_item(body: NightQueueRequest, user: dict = Depends(get_current_user)):
    try:
        item = await enqueue_item(
            user["id"],
            body.kind,
            change_id=body.change_id,
            repo_id=body.repo_id,
            bug_report=body.bug_report,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await log_audit("night_queue_add", user_id=str(user["id"]),
                    details={"kind": body.kind, "title": item["title"][:120]})
    return item


@router.delete("/night-queue/{item_id}", response_model=dict)
async def cancel_night_item(item_id: str, user: dict = Depends(get_current_user)):
    if not await cancel_item(item_id, user["id"]):
        raise HTTPException(status_code=404, detail="条目不存在或已在执行")
    return {"ok": True}

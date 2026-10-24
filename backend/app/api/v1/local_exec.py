"""本地执行器接口：nova.py agent 长轮询领取命令、回传执行结果。

请求行由 local_run_command 工具写入；本地执行器用用户自己的凭据认证，
只能看到并处理属于该用户的派发。命令在本机的最终执行前还会经用户确认。
"""
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.security.audit import log_audit
from app.core.security.auth import get_current_user
from app.db import execute

router = APIRouter()

# 本地执行器在线状态：agent 每 3 秒轮询一次 pending，即天然心跳。
# 进程内记录（单 worker 部署）；重启后 30 秒内心跳恢复即自动转绿。
_AGENT_LAST_SEEN: dict[int, float] = {}
_AGENT_ONLINE_WINDOW_S = 30


class LocalExecClaim(BaseModel):
    id: str
    cwd: str
    command: str
    kind: str = "shell"
    file_path: str | None = None
    content: str | None = None


class LocalExecResult(BaseModel):
    ok: bool = True
    output: str = Field(default="", max_length=100_000)
    exit_code: int = 0


@router.get("/local/exec/pending", response_model=list[LocalExecClaim])
async def claim_pending(user: dict = Depends(get_current_user)):
    """本地执行器长轮询：原子地把 pending 置为 claimed 并返回，避免重复领取。"""
    _AGENT_LAST_SEEN[user["id"]] = time.time()
    rows = await execute(
        """
        UPDATE local_exec_requests SET status = 'claimed', updated_at = now()
        WHERE id IN (
            SELECT id FROM local_exec_requests
            WHERE user_id = %s AND status = 'pending'
            ORDER BY created_at
            LIMIT 5
        )
        RETURNING id, cwd, command, kind, file_path, content
        """,
        (user["id"],),
    )
    return [
        LocalExecClaim(id=str(row[0]), cwd=row[1], command=row[2], kind=row[3],
                       file_path=row[4], content=row[5])
        for row in rows
    ]


@router.post("/local/exec/{request_id}/result", response_model=dict)
async def submit_result(request_id: str, body: LocalExecResult, user: dict = Depends(get_current_user)):
    try:
        rid = str(uuid.UUID(request_id))
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的请求 ID")
    rows = await execute(
        """
        UPDATE local_exec_requests
        SET status = %s, output = %s, exit_code = %s, updated_at = now()
        WHERE id = %s AND user_id = %s AND status IN ('pending', 'claimed')
        RETURNING id
        """,
        ("done" if body.ok else "error", body.output, body.exit_code, rid, user["id"]),
    )
    if not rows:
        raise HTTPException(status_code=404, detail="请求不存在或已被处理")
    await log_audit(
        "local_exec_result",
        user_id=str(user["id"]),
        details={"request_id": rid, "exit_code": body.exit_code, "ok": body.ok},
    )
    return {"ok": True}


@router.get("/local/exec/status", response_model=dict)
async def local_exec_status(user: dict = Depends(get_current_user)):
    """对话界面显示本机执行器是否在线（基于轮询心跳，30 秒窗口）。"""
    seen = _AGENT_LAST_SEEN.get(user["id"], 0.0)
    age = time.time() - seen if seen else None
    return {
        "connected": age is not None and age < _AGENT_ONLINE_WINDOW_S,
        "last_seen_age": int(age) if age is not None else None,
    }

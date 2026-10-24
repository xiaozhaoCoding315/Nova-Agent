"""Builder endpoints: greenfield plan + file proposal with approval gates."""
import uuid

from fastapi import APIRouter, Depends, HTTPException

from app.core.builder import engine
from app.core.conflicts import ConflictError
from app.core.indexing.pipeline import get_repo
from app.core.jobs.service import (
    enqueue_builder_files,
    enqueue_builder_plan,
    enqueue_index,
    enqueue_verify,
)
from app.core.sandbox.runtime import sandbox_status
from app.core.security.auth import get_current_user
from app.core.security.limits import check_job_quota, check_sandbox_quota, ensure_token_budget
from app.db import execute, query
from app.models.schemas import (
    BuilderActionOut,
    BuilderApplyOut,
    BuilderCreate,
    BuilderDesignRequest,
    BuilderFeedback,
    BuilderPlanOut,
    BuilderProposalOut,
    RepoOut,
    VerifyActionOut,
    VerifyResultOut,
)

router = APIRouter()

DESIGN_SYSTEM_PROMPT = """你是 Nova 的项目设计搭档。用户想做一个软件项目，你通过轻松的多轮对话帮他把想法打磨成可以直接生成的方案。

规则：
1. 每轮只问 1-2 个当下最关键的问题（目标用户、核心功能、数据实体、主要页面或接口、技术约束），不要一次抛一串问题
2. 用户回答后先用一句话确认你的理解，再继续问
3. 不写代码、不聊实现细节
4. 当信息足够（通常 2-4 轮），主动输出最终需求，格式必须是：
[方案定稿]
（一段完整、可直接交给代码生成的需求：项目目标、功能清单、数据模型与主要字段、主要页面或 API、非功能要求）
5. 输出定稿后不再提问；用户要求调整时修订后重新输出定稿
6. 全程使用中文，口吻自然，像一个耐心的技术朋友"""


async def _design_reply(messages: list[dict], user: dict, stack: str) -> tuple[str, dict | None]:
    import asyncio

    from app.config import settings
    from app.core.llm.factory import get_llm

    llm = await get_llm(user["id"], purpose="plan")
    full = [
        {"role": "system", "content": DESIGN_SYSTEM_PROMPT + f"\n目标技术栈：{stack}"},
        *messages,
    ]
    parts: list[str] = []
    usage: dict | None = None
    async with asyncio.timeout(settings.llm_timeout):
        async for event in llm.astream_with_tools(full, []):
            if isinstance(event, str):
                parts.append(event)
            elif event.get("type") == "content":
                parts.append(event.get("content") or "")
            elif event.get("type") == "usage":
                usage = event.get("usage")
    return "".join(parts), usage


@router.post("/repos/builder/design", response_model=dict)
async def builder_design_chat(body: BuilderDesignRequest, user: dict = Depends(get_current_user)):
    """Conversational project design: agent asks, user answers, plan converges."""
    await ensure_token_budget(user)
    history = [
        {"role": m.role, "content": m.content} for m in body.messages[-40:]
    ]
    try:
        reply, usage = await _design_reply(history, user, body.stack)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"设计对话失败：{str(exc)[:200]}")
    if usage:
        from app.core.llm.usage import record_usage
        await record_usage(user["id"], None, usage, source="builder")
    return {"reply": reply}


async def _own_repo(repo_id: str, user_id: int) -> dict:
    repo = await engine.load_builder(repo_id)
    if not repo or repo["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="项目不存在")
    return repo


@router.post("/repos/builder", response_model=RepoOut)
async def create_builder_project(body: BuilderCreate, user: dict = Depends(get_current_user)):
    check_job_quota(user, "builder")
    await ensure_token_budget(user)
    repo_id = str(uuid.uuid4())
    from app.core.storage.user_storage import repo_container
    root = repo_container(user["id"], repo_id)
    root.mkdir(parents=True, exist_ok=True)
    await execute(
        "INSERT INTO repos (id, user_id, name, source, root_path, status, kind, stack_mode, brief, rules) "
        "VALUES (%s, %s, %s, %s, %s, 'planning', 'builder', %s, %s, %s)",
        (repo_id, user["id"], body.name.strip(), f"builder:{body.name.strip()}",
         str(root), body.stack, body.requirements, body.rules or ""),
    )
    await enqueue_builder_plan(repo_id, user_id=user["id"])
    return {
        "id": repo_id, "name": body.name.strip(), "source": f"builder:{body.name.strip()}",
        "status": "planning", "kind": "builder", "stats": {},
    }


@router.get("/repos/{repo_id}/plan", response_model=BuilderPlanOut)
async def get_plan(repo_id: str, user: dict = Depends(get_current_user)):
    repo = await _own_repo(repo_id, user["id"])
    return {
        "status": repo["status"],
        "plan": repo["plan"],
        "error": repo["error"],
        "brief": repo["brief"],
        "rules": repo["rules"],
    }


@router.post("/repos/{repo_id}/plan/generate", response_model=BuilderActionOut)
async def regenerate_plan(repo_id: str, user: dict = Depends(get_current_user)):
    repo = await _own_repo(repo_id, user["id"])
    if repo["status"] in ("planning", "generating"):
        raise HTTPException(status_code=400, detail="方案正在生成中")
    await ensure_token_budget(user)
    await enqueue_builder_plan(repo_id, user_id=user["id"])
    return {"ok": True, "status": "planning"}


@router.post("/repos/{repo_id}/plan/approve", response_model=BuilderActionOut)
async def approve_plan(repo_id: str, user: dict = Depends(get_current_user)):
    await _own_repo(repo_id, user["id"])
    try:
        await engine.approve_plan(repo_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "status": "approved"}


@router.post("/repos/{repo_id}/generate", response_model=BuilderActionOut)
async def generate_files(
    repo_id: str,
    body: BuilderFeedback | None = None,
    user: dict = Depends(get_current_user),
):
    repo = await _own_repo(repo_id, user["id"])
    if repo["status"] not in ("approved", "review"):
        raise HTTPException(status_code=400, detail="请先确认方案，再生成代码")
    await ensure_token_budget(user)
    await enqueue_builder_files(
        repo_id, (body.feedback if body else "") or "", user_id=user["id"]
    )
    return {"ok": True, "status": "generating"}


@router.get("/repos/{repo_id}/proposal", response_model=BuilderProposalOut)
async def get_proposal(repo_id: str, user: dict = Depends(get_current_user)):
    repo = await _own_repo(repo_id, user["id"])
    return {"status": repo["status"], "proposal": repo["proposal"], "error": repo["error"]}


@router.post("/repos/{repo_id}/proposal/approve", response_model=BuilderApplyOut)
async def approve_proposal(repo_id: str, user: dict = Depends(get_current_user)):
    repo = await _own_repo(repo_id, user["id"])
    if repo["status"] != "review":
        raise HTTPException(status_code=400, detail="当前没有待审阅的代码提案")
    check_job_quota(user, "reindex")
    try:
        applied = await engine.apply_proposal(repo)
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await enqueue_index(repo_id, reindex=True, user_id=user["id"])
    # Smoke boot: once written and indexed, the project must actually run.
    from app.config import settings as app_settings
    smoke_job_id = None
    if app_settings.builder_smoke_enabled:
        from app.core.jobs.runner import runner
        if runner.has("builder_smoke"):
            smoke_job_id = await runner.enqueue(
                "builder_smoke",
                {"repo_id": repo_id, "user_id": user["id"]},
                user_id=user["id"],
                idempotency_key=f"smoke:{repo_id}:{applied and len(applied)}",
            )
    return {"ok": True, "applied": applied, "status": "indexing", "smoke_job_id": smoke_job_id}


@router.post("/repos/{repo_id}/proposal/reject", response_model=BuilderActionOut)
async def reject_proposal(repo_id: str, user: dict = Depends(get_current_user)):
    await _own_repo(repo_id, user["id"])
    try:
        await engine.reject_proposal(repo_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "status": "approved"}


@router.post("/repos/{repo_id}/verify", response_model=VerifyActionOut)
async def verify_repo(repo_id: str, user: dict = Depends(get_current_user)):
    """Queue a stack-aware verification job (Python / Node / fullstack)."""
    repo = await get_repo(repo_id, user["id"])
    if not repo:
        raise HTTPException(status_code=404, detail="仓库不存在")
    if repo["status"] != "ready":
        raise HTTPException(status_code=400, detail="仓库尚未完成索引，无法验证")

    status = await sandbox_status()
    if not status.get("available") and not status.get("node_available"):
        raise HTTPException(status_code=400, detail=f"沙箱不可用：{status['reason']}")
    check_job_quota(user, "verify")
    await check_sandbox_quota(user)

    job_id = await enqueue_verify(repo_id, user["id"])
    return {"ok": True, "job_id": job_id}


@router.get("/repos/{repo_id}/verify", response_model=VerifyResultOut | None)
async def last_verify(repo_id: str, user: dict = Depends(get_current_user)):
    repo = await get_repo(repo_id, user["id"])
    if not repo:
        raise HTTPException(status_code=404, detail="仓库不存在")
    rows = await query("SELECT last_check FROM repos WHERE id = %s", (repo_id,))
    return (rows[0][0] if rows else None) or None
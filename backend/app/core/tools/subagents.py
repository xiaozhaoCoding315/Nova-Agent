"""spawn_agents: parallel read-only sub-agent research."""
import asyncio
import json
import uuid

from app.config import settings
from app.core.agent.subagent import run_subagent
from app.core.indexing.pipeline import get_repo
from app.core.security.redaction import redact_text
from app.core.tools.base import ToolBusinessError, ToolContext, ToolDefinition


def _normalize_tasks(raw, ctx: ToolContext) -> list[dict]:
    if not isinstance(raw, list) or not raw:
        raise ToolBusinessError("tasks 必须是非空数组")
    if len(raw) > max(int(settings.subagent_max_tasks), 1):
        raise ToolBusinessError(f"一次最多 {settings.subagent_max_tasks} 个子任务")
    if not ctx.repo_ids:
        raise ToolBusinessError("子代理需要至少一个关联仓库")

    tasks: list[dict] = []
    for index, item in enumerate(raw, 1):
        if not isinstance(item, dict):
            raise ToolBusinessError(f"第 {index} 个子任务格式不正确")
        title = str(item.get("title") or "").strip()[:80]
        prompt = str(item.get("prompt") or "").strip()
        if not title:
            raise ToolBusinessError(f"第 {index} 个子任务缺少 title")
        if len(prompt) < 10 or len(prompt) > 4000:
            raise ToolBusinessError(f"第 {index} 个子任务 prompt 需为 10–4000 字符")
        repo_id = str(item.get("repo_id") or "").strip() or None
        if repo_id and repo_id not in ctx.repo_ids:
            raise ToolBusinessError(
                f"第 {index} 个子任务的 repo_id 不在当前会话仓库范围内"
            )
        tasks.append({
            "title": title,
            "prompt": prompt,
            "repo_ids": [repo_id] if repo_id else list(ctx.repo_ids),
        })
    return tasks


async def _repo_meta(repo_ids: list[str], user_id: int) -> dict[str, dict]:
    meta: dict[str, dict] = {}
    for repo_id in dict.fromkeys(repo_ids):
        repo = await get_repo(repo_id, user_id)
        if repo:
            meta[repo_id] = {
                "id": repo["id"],
                "name": repo["name"],
                "root_path": repo.get("root_path") or "",
                "rules": repo.get("rules") or "",
            }
    return meta


def _failed_task(task_id: str, title: str, error: str) -> dict:
    """Failed-task result with the same shape as ``run_subagent``."""
    return {
        "id": task_id, "title": title, "status": "failed",
        "summary": "", "findings": [], "files": [], "rounds": 0,
        "tools": [], "tokens": {"prompt": 0, "completion": 0}, "ms": 0,
        "citations": {
            "citations": [], "executed": False, "verified": 0,
            "missing": 0, "out_of_range": 0, "skipped": 0,
        },
        "error": redact_text(str(error))[:300],
    }


async def spawn_agents(args: dict, ctx: ToolContext) -> dict:
    if ctx.agent_depth > 0:
        raise ToolBusinessError("子代理不能继续派生子代理")

    tasks = _normalize_tasks(args.get("tasks"), ctx)
    total = ctx.subagent_tasks_used + len(tasks)
    if total > max(int(settings.subagent_turn_limit), 1):
        raise ToolBusinessError(
            f"单轮对话最多运行 {settings.subagent_turn_limit} 个子任务，已用完"
        )

    wanted = sorted({repo_id for task in tasks for repo_id in task["repo_ids"]})
    meta = await _repo_meta(wanted, int(ctx.user["id"]))
    roots = {
        repo_id: item["root_path"]
        for repo_id, item in meta.items() if item.get("root_path")
    }

    async def emit(payload: dict) -> None:
        if ctx.output_queue is not None:
            await ctx.output_queue.put(
                ("subagent", json.dumps(payload, ensure_ascii=False))
            )

    semaphore = asyncio.Semaphore(max(int(settings.subagent_max_parallel), 1))

    async def run_one(task: dict) -> dict:
        task_id = f"sa-{uuid.uuid4().hex[:8]}"
        async with semaphore:
            try:
                return await run_subagent(
                    user=ctx.user,
                    session_id=ctx.session_id,
                    turn_id=ctx.turn_id,
                    task_id=task_id,
                    title=task["title"],
                    prompt=task["prompt"],
                    repo_ids=task["repo_ids"],
                    repos=[
                        meta[repo_id] for repo_id in task["repo_ids"] if repo_id in meta
                    ],
                    repo_roots={
                        repo_id: roots[repo_id]
                        for repo_id in task["repo_ids"] if repo_id in roots
                    },
                    emit=emit,
                    model=ctx.model,
                    overrides=ctx.llm_overrides,
                )
            except Exception as exc:  # noqa: BLE001 — one task must not sink the rest
                return _failed_task(task_id, task["title"], str(exc))

    # Count before fan-out: if the harness cancels/times out this call, the
    # tasks still consumed their per-turn quota and must not be reusable.
    ctx.subagent_tasks_used = total
    results = await asyncio.gather(*(run_one(task) for task in tasks))
    return {
        "tasks": results,
        "total": len(results),
        "ok_count": sum(
            1 for item in results if item.get("status") in ("ok", "partial")
        ),
        "note": (
            "子代理只读；结果中的文件行号已做引用校验，"
            "仍需主代理复核关键结论。"
        ),
    }


_WAVES = max(
    1,
    (max(int(settings.subagent_max_tasks), 1)
     + max(int(settings.subagent_max_parallel), 1) - 1)
    // max(int(settings.subagent_max_parallel), 1),
)
TOOL_TIMEOUT = _WAVES * int(settings.subagent_timeout) + 60


TOOL = ToolDefinition(
    name="spawn_agents",
    description=(
        f"把一个任务拆成 1–{settings.subagent_max_tasks} 个互不依赖的只读调研/审查子任务，"
        "并行交给子代理执行。"
        "子代理有独立上下文，不能修改文件、执行命令、联网或再派生子代理；"
        "返回每个子任务的结论、关键发现（文件:行号）、引用校验与用量。"
        "仅在任务可并行拆分时使用；简单查询或强顺序依赖的任务不要用。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "tasks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "不超过 80 字符的子任务标题"},
                        "prompt": {"type": "string", "description": "10–4000 字符的具体调研要求"},
                        "repo_id": {"type": "string", "description": "可选，必须是当前会话关联仓库的 id"},
                    },
                    "required": ["title", "prompt"],
                },
            },
        },
        "required": ["tasks"],
    },
    func=spawn_agents,
    timeout=max(TOOL_TIMEOUT, 120),
    category="read",
    capabilities=[],
    parallel_safe=False,
    streaming=True,
)

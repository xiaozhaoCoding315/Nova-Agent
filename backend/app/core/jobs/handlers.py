"""Built-in job handlers.

Handlers are intentionally thin: they call the existing domain engines and
translate their terminal state into a job failure/success.  This keeps the
queue generic while preserving the engines' own status fields for the UI.
"""
import structlog

from app.core.jobs.models import JobContext, JobFailed

logger = structlog.get_logger()


async def _index(ctx: JobContext) -> dict:
    from app.core.indexing.pipeline import get_repo, index_repo, reindex_repo

    repo_id = str(ctx.payload["repo_id"])
    await ctx.check_cancel()
    await ctx.update(progress=0.05, step="准备索引")
    if ctx.payload.get("reindex"):
        await reindex_repo(repo_id, ctx=ctx)
    else:
        await index_repo(repo_id, ctx=ctx)
    repo = await get_repo(repo_id)
    if not repo:
        raise JobFailed("仓库不存在")
    if repo["status"] != "ready":
        raise JobFailed(repo.get("error") or "索引未完成")
    return {"repo_id": repo_id, "status": "ready", "stats": repo.get("stats") or {}}


async def _task(ctx: JobContext) -> dict:
    from app.core.tasks.engine import run_task
    from app.db import query

    task_id = str(ctx.payload["task_id"])
    await ctx.check_cancel()
    await ctx.update(progress=0.02, step="准备修复任务")
    await run_task(task_id, ctx=ctx)
    rows = await query("SELECT status, result FROM tasks WHERE id = %s", (task_id,))
    if not rows:
        raise JobFailed("任务不存在")
    status, result = rows[0][0], rows[0][1] or {}
    if status not in ("ready", "applied"):
        raise JobFailed((result or {}).get("error") or f"任务未成功（{status}）")
    return {"task_id": task_id, "status": status}


async def _builder_plan(ctx: JobContext) -> dict:
    from app.core.builder import engine

    repo_id = str(ctx.payload["repo_id"])
    await ctx.check_cancel()
    await ctx.update(progress=0.05, step="生成项目方案")
    await engine.generate_plan(repo_id, ctx=ctx)
    repo = await engine.load_builder(repo_id)
    if not repo:
        raise JobFailed("项目不存在")
    if repo["status"] == "failed":
        raise JobFailed(repo.get("error") or "方案生成失败")
    return {"repo_id": repo_id, "status": repo["status"]}


async def _builder_files(ctx: JobContext) -> dict:
    from app.core.builder import engine

    repo_id = str(ctx.payload["repo_id"])
    feedback = str(ctx.payload.get("feedback") or "")
    await ctx.check_cancel()
    await ctx.update(progress=0.05, step="生成项目文件")
    await engine.generate_files(repo_id, feedback, ctx=ctx)
    repo = await engine.load_builder(repo_id)
    if not repo:
        raise JobFailed("项目不存在")
    if repo["status"] != "review":
        raise JobFailed(repo.get("error") or f"文件提案未生成（{repo['status']}）")
    return {"repo_id": repo_id, "status": repo["status"]}


async def _session_summary(ctx: JobContext) -> dict:
    from app.core.memory.summary import maybe_summarize

    session_id = str(ctx.payload["session_id"])
    user_id = int(ctx.payload["user_id"])
    await ctx.check_cancel()
    await ctx.update(progress=0.1, step="压缩会话记忆")
    added = await maybe_summarize(session_id, user_id, ctx=ctx)
    return {"session_id": session_id, "summarized": added}


async def _change_spec(ctx: JobContext) -> dict:
    from app.core.changes import service
    from app.core.jobs.models import JobCanceled

    change_id = str(ctx.payload["change_id"])
    await ctx.check_cancel()
    await ctx.update(progress=0.1, step="起草 SPEC")
    try:
        await service.draft_spec(change_id, ctx=ctx)
    except JobCanceled:
        raise
    except Exception as exc:  # noqa: BLE001
        await service.set_change_status(change_id, "failed", str(exc))
        raise
    return {"change_id": change_id, "status": "draft"}


async def _change_plan(ctx: JobContext) -> dict:
    from app.core.changes import service
    from app.core.jobs.models import JobCanceled

    change_id = str(ctx.payload["change_id"])
    await ctx.check_cancel()
    await ctx.update(progress=0.1, step="规划变更任务")
    try:
        await service.generate_plan(change_id, ctx=ctx)
    except JobCanceled:
        raise
    except Exception as exc:  # noqa: BLE001
        await service.set_change_status(change_id, "failed", str(exc))
        raise
    return {"change_id": change_id, "status": "plan_ready"}


async def _change_execute(ctx: JobContext) -> dict:
    from app.core.changes.executor import execute_change
    from app.core.changes import service
    from app.core.jobs.models import JobCanceled

    change_id = str(ctx.payload["change_id"])
    user_id = int(ctx.payload["user_id"])
    await ctx.check_cancel()
    try:
        result = await execute_change(change_id, user_id, ctx=ctx)
    except JobCanceled:
        raise
    except Exception as exc:  # noqa: BLE001
        await service.set_change_status(change_id, "failed", str(exc))
        raise
    return result


async def _verify(ctx: JobContext) -> dict:
    import json

    from app.core.indexing.pipeline import get_repo
    from app.core.jobs.models import JobCanceled
    from app.core.verify.service import run_verification
    from app.db import execute, query

    repo_id = str(ctx.payload["repo_id"])
    user_id = int(ctx.job.user_id or ctx.payload.get("user_id") or 0)
    await ctx.check_cancel()
    await ctx.update(progress=0.05, step="运行验证")
    repo = await get_repo(repo_id)
    if not repo:
        raise JobFailed("仓库不存在")
    rows = await query("SELECT id, username, role FROM users WHERE id = %s", (user_id,))
    if not rows:
        raise JobFailed("验证归属账号不存在")
    user = {"id": rows[0][0], "username": rows[0][1], "role": rows[0][2]}
    try:
        result = await run_verification(repo, user)
    except JobCanceled:
        raise
    await execute(
        "UPDATE repos SET last_check = %s, updated_at = now() WHERE id = %s",
        (json.dumps(result, ensure_ascii=False), repo_id),
    )
    if result.get("status") == "failed":
        raise JobFailed("验证未通过，请查看步骤输出")
    await ctx.update(progress=0.98, step="验证完成")
    return {
        "repo_id": repo_id,
        "status": result.get("status"),
        "stack": result.get("stack"),
        "steps": [
            {"name": step.get("name"), "status": step.get("status"), "exit_code": step.get("exit_code")}
            for step in result.get("steps", [])
        ],
    }


def register_all(runner) -> None:
    """Idempotently register the built-in handlers."""
    if not runner.has("index"):
        runner.register("index", _index, concurrency=1)
    if not runner.has("task"):
        runner.register("task", _task, concurrency=1)
    if not runner.has("builder_plan"):
        runner.register("builder_plan", _builder_plan, concurrency=1)
    if not runner.has("builder_files"):
        runner.register("builder_files", _builder_files, concurrency=1)
    if not runner.has("session_summary"):
        runner.register("session_summary", _session_summary, concurrency=2)
    if not runner.has("verify"):
        runner.register("verify", _verify, concurrency=1)
    if not runner.has("change_spec"):
        runner.register("change_spec", _change_spec, concurrency=1)
    if not runner.has("change_plan"):
        runner.register("change_plan", _change_plan, concurrency=1)
    if not runner.has("change_execute"):
        runner.register("change_execute", _change_execute, concurrency=1)

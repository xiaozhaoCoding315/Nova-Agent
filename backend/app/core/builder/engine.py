"""Builder: greenfield project plan → file proposal → human-approved write.

MVP scope: Python backend (FastAPI + sqlite3 + pytest). The builder never
executes generated code and never writes without an explicit approval; after
approval the normal indexing pipeline takes over.
"""
import json
from pathlib import Path

import structlog

from app.core.conflicts import ConflictError
from app.core.llm.json_call import llm_json
from app.core.security.limits import ensure_token_budget
from app.core.security.paths import (
    UnsafePathError, is_secret_path, resolve_repo_path, try_normalize_relpath,
)
from app.core.security.test_guard import assert_changes_preserve_tests
from app.db import execute, query

logger = structlog.get_logger()

MAX_FILES = 30
MAX_FILE_CHARS = 120_000
MAX_TOTAL_CHARS = 400_000

PLAN_PROMPT = """你是资深全栈架构师。请为下面的需求设计一个从 0 到 1 可落地的 Python 后端项目方案。

需求：
{requirements}

项目约定（AGENTS.md）：
{rules}

约束：
- 技术栈固定为 Python 3.12 + FastAPI + SQLite（标准库 sqlite3）+ pytest
- 单体结构，避免重型依赖；requirements.txt 只放 fastapi / uvicorn / pytest / httpx
- 面向演示与教学级质量：结构清晰、有基础错误处理与测试

只输出 JSON（不要 markdown 代码块）：
{{
 "summary": "一句话概述",
 "stack": ["Python 3.12", "FastAPI", "SQLite", "pytest"],
 "structure": [{{"path": "app/main.py", "purpose": "应用入口"}}],
 "data_model": [{{"table": "items", "fields": ["id INTEGER PRIMARY KEY", "title TEXT NOT NULL"]}}],
 "api": [{{"method": "GET", "path": "/items", "description": "列出全部"}}],
 "milestones": [{{"name": "基础骨架", "tasks": ["建表", "健康检查"], "verification": "pytest tests/ -q"}}],
 "risks": ["..."]
}}"""

FILES_PROMPT = """根据已确认的方案，生成完整可运行的 Python 后端项目文件。

方案：
{plan}

项目约定：
{rules}

{feedback}

要求：
- FastAPI + sqlite3 + pytest；requirements.txt 只包含 fastapi、uvicorn、pytest、httpx
- 必须包含 README.md、requirements.txt、.gitignore、AGENTS.md、app/ 下的实现、tests/ 下的 pytest 用例
- 每个文件给出完整内容，不要省略或用占位符
- 文件总数 ≤ {max_files}；路径为相对路径
- 代码要能直接运行：uvicorn app.main:app

只输出 JSON：
{{"files": [{{"path": "app/main.py", "content": "..."}}], "notes": "实现要点"}}"""


async def _set(repo_id: str, **fields) -> None:
    sets, params = [], []
    for key, value in fields.items():
        sets.append(f"{key} = %s")
        params.append(json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value)
    sets.append("updated_at = now()")
    await execute(f"UPDATE repos SET {', '.join(sets)} WHERE id = %s", (*params, repo_id))


async def load_builder(repo_id: str) -> dict | None:
    rows = await query(
        "SELECT id, user_id, name, root_path, status, kind, brief, rules, plan, proposal, error "
        "FROM repos WHERE id = %s",
        (repo_id,),
    )
    if not rows:
        return None
    r = rows[0]
    return {
        "id": str(r[0]), "user_id": r[1], "name": r[2], "root_path": r[3],
        "status": r[4], "kind": r[5], "brief": r[6] or "", "rules": r[7] or "",
        "plan": r[8] or {}, "proposal": r[9] or {}, "error": r[10],
    }


def _clean_plan(data: dict) -> dict:
    def take(key: str, limit: int) -> list:
        value = data.get(key)
        return value[:limit] if isinstance(value, list) else []

    return {
        "summary": str(data.get("summary", ""))[:1000],
        "stack": take("stack", 10),
        "structure": take("structure", 50),
        "data_model": take("data_model", 30),
        "api": take("api", 50),
        "milestones": take("milestones", 10),
        "risks": take("risks", 15),
        "generated_at": None,
    }


def validate_files(items) -> dict[str, str]:
    """Path-safe, bounded file map from the LLM's list/dict payload."""
    if isinstance(items, dict):
        items = [{"path": k, "content": v} for k, v in items.items()]
    files: dict[str, str] = {}
    total = 0
    for item in items or []:
        if not isinstance(item, dict):
            continue
        path = try_normalize_relpath(item.get("path", ""))
        content = item.get("content")
        if not path or is_secret_path(path):
            continue
        if not isinstance(content, str) or not content.strip():
            continue
        content = content[:MAX_FILE_CHARS]
        total += len(content)
        if len(files) >= MAX_FILES or total > MAX_TOTAL_CHARS:
            break
        files[path] = content
    return files


async def generate_plan(repo_id: str, ctx=None) -> None:
    repo = await load_builder(repo_id)
    if not repo:
        return
    try:
        if ctx:
            await ctx.check_cancel()
        await _set(repo_id, status="planning", error=None)
        await ensure_token_budget(user_id=repo["user_id"])
        data = await llm_json(
            PLAN_PROMPT.format(requirements=repo["brief"][:6000], rules=repo["rules"][:3000] or "（无）"),
            user_id=repo["user_id"], source="builder",
        )
        if ctx:
            await ctx.check_cancel()
        plan = _clean_plan(data)
        if not plan["summary"]:
            raise ValueError("方案缺少 summary")
        await _set(repo_id, plan=plan, status="plan_ready")
        logger.info("builder_plan_ready", repo_id=repo_id)
    except Exception as exc:  # noqa: BLE001
        from app.core.jobs.models import JobCanceled
        if isinstance(exc, JobCanceled):
            logger.info("builder_plan_canceled", repo_id=repo_id)
            await _set(repo_id, status="failed", error="已取消")
            raise
        logger.exception("builder_plan_failed", repo_id=repo_id)
        await _set(repo_id, status="failed", error=f"方案生成失败：{type(exc).__name__}: {exc}")


async def approve_plan(repo_id: str) -> None:
    repo = await load_builder(repo_id)
    if not repo:
        raise RuntimeError("项目不存在")
    if repo["status"] != "plan_ready":
        raise RuntimeError("当前状态不能确认方案")
    await _set(repo_id, status="approved", error=None)


async def generate_files(repo_id: str, feedback: str = "", ctx=None) -> None:
    repo = await load_builder(repo_id)
    if not repo:
        return
    previous = repo["status"]
    try:
        if ctx:
            await ctx.check_cancel()
        if previous not in ("approved", "review"):
            raise RuntimeError("请先确认方案，再生成代码")
        await _set(repo_id, status="generating", error=None)
        await ensure_token_budget(user_id=repo["user_id"])
        data = await llm_json(
            FILES_PROMPT.format(
                plan=json.dumps(repo["plan"], ensure_ascii=False)[:20000],
                rules=repo["rules"][:3000] or "（无）",
                feedback=f"上一轮审阅反馈（请针对性修改）：{feedback[:2000]}" if feedback else "",
                max_files=MAX_FILES,
            ),
            user_id=repo["user_id"], source="builder",
        )
        if ctx:
            await ctx.check_cancel()
        files = validate_files(data.get("files"))
        if not files:
            raise ValueError("模型没有产出有效文件")
        root = Path(repo["root_path"]).resolve()
        base_files: dict[str, str | None] = {}
        for path in files:
            try:
                target = resolve_repo_path(root, path)
            except UnsafePathError:
                continue
            base_files[path] = (
                target.read_text(encoding="utf-8", errors="replace") if target.is_file() else None
            )
        proposal = {
            "files": [{"path": p, "content": c} for p, c in files.items()],
            "base_files": base_files,
            "notes": str(data.get("notes", ""))[:3000],
            "feedback": feedback[:2000],
        }
        await _set(repo_id, proposal=proposal, status="review")
        logger.info("builder_proposal_ready", repo_id=repo_id, files=len(files))
    except Exception as exc:  # noqa: BLE001
        from app.core.jobs.models import JobCanceled
        if isinstance(exc, JobCanceled):
            logger.info("builder_generate_canceled", repo_id=repo_id)
            await _set(repo_id, status="approved", error="已取消")
            raise
        logger.exception("builder_generate_failed", repo_id=repo_id)
        await _set(
            repo_id,
            status="approved" if previous in ("approved", "review") else "plan_ready",
            error=f"代码生成失败：{type(exc).__name__}: {exc}",
        )


async def reject_proposal(repo_id: str) -> None:
    repo = await load_builder(repo_id)
    if not repo:
        raise RuntimeError("项目不存在")
    if repo["status"] != "review":
        raise RuntimeError("当前没有待审阅的代码提案")
    await _set(repo_id, proposal=None, status="approved")


async def apply_proposal(repo: dict) -> list[str]:
    """Write the approved proposal into the project workspace."""
    proposal = repo.get("proposal") or {}
    items = proposal.get("files") or []
    if not items:
        raise RuntimeError("没有可写入的文件")

    root = Path(repo["root_path"]).resolve()
    root.mkdir(parents=True, exist_ok=True)

    for path, expected in (proposal.get("base_files") or {}).items():
        try:
            target = resolve_repo_path(root, path)
        except UnsafePathError:
            continue
        current = target.read_text(encoding="utf-8", errors="replace") if target.is_file() else None
        if current != expected:
            raise ConflictError(f"文件在提案生成后已被修改：{path}，请重新生成提案")

    changes: dict[str, str] = {}
    for item in items:
        path = try_normalize_relpath(item.get("path", ""))
        content = item.get("content")
        if path and is_secret_path(path):
            raise RuntimeError(f"拒绝写入密钥/凭据文件：{path}")
        if not path or not isinstance(content, str) or not content.strip():
            continue
        changes[path] = content
    if not changes:
        raise RuntimeError("提案中没有可写入的文件")

    base: dict[str, str | None] = {}
    for path in changes:
        target = resolve_repo_path(root, path)
        base[path] = target.read_text(encoding="utf-8", errors="replace") if target.is_file() else None
    assert_changes_preserve_tests(changes, base)

    applied: list[str] = []
    for path, content in changes.items():
        try:
            target = resolve_repo_path(root, path)
        except UnsafePathError:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        applied.append(path)

    await _set(repo_id=repo["id"], proposal=None, status="indexing", error=None,
               source=f"builder:{repo['name']}")
    from app.core.git_ops.service import auto_commit
    await auto_commit(root, "builder: initial scaffold")
    return applied
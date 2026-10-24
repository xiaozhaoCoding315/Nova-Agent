"""Deterministic change executor: SPEC task -> code -> gate -> proposal.

The executor is deliberately serial.  Only read-only research may run in
parallel later; writes must not race on the same workspace.  Every task ends
with a real sandbox gate (or an explicit ``unsupported`` result), and failures
are fed back as failure summaries with a bounded retry budget.
"""
import fnmatch
import json
import time

import structlog

from app.core.changes import service
from app.core.changes.templates import template_for
from app.core.editing.service import create_edit
from app.core.indexing.pipeline import get_repo
from app.core.llm.json_call import llm_json
from app.core.rag.retriever import retrieve
from app.core.review.service import review_diff
from app.core.security.limits import ensure_token_budget
from app.core.security.paths import is_secret_path, try_normalize_relpath
from app.core.security.test_guard import assert_changes_preserve_tests
from app.core.tools.run_code import _collect_repo_files
from app.core.verify.service import run_verification
from app.db import execute, query

logger = structlog.get_logger()

MAX_FILES_PER_TASK = 6
MAX_TASK_CHARS = 120_000
MAX_REPAIR_ATTEMPTS = 3
MAX_CONTEXT_FILES = 6

_TASK_PROMPT = """你是全栈开发 Agent，正在执行一个已批准变更计划中的单个任务。

变更 SPEC：
{spec}

当前任务：
标题：{task_title}
类型：{task_kind}（{task_label}）
允许修改：{in_scope}
禁止修改：{out_scope}
验收标准：{acceptance}

任务提示：
{template_hint}

项目约定：
{rules}

项目文件（节选）：
{tree}

相关文件（当前完整内容）：
{files}

只输出 JSON（不要 markdown）：
{{
  "files": {{"相对路径": "修改后的完整文件内容"}},
  "notes": "本任务做了什么、为什么",
  "tests": ["新增/涉及的测试"]
}}

规则：
- 只能修改任务允许范围内的文件；禁止修改 out_scope。
- files 必须是完整文件内容，不是 diff。不要输出未修改的文件。
- 必须保留已有测试，不得删除测试或新增 skip。
- 不要做与任务无关的重构。
- 最多修改 {max_files} 个文件；无法完成任务时返回空 files 并在 notes 说明原因。"""

_REPAIR_PROMPT = """上一轮实现没有通过验证门。请根据真实失败输出修正实现。

当前任务：
{task_title}

验收标准：
{acceptance}

失败摘要：
{failure}

当前任务涉及的文件：
{files}

只输出与上一轮相同的 JSON 结构（files / notes / tests）。仍然只能修改允许范围内的文件，
必须输出完整文件内容，不得删除或跳过测试。"""


def _matches(path: str, patterns: list[str]) -> bool:
    for raw in patterns:
        pattern = str(raw or "").strip().lstrip("./")
        if not pattern:
            continue
        if fnmatch.fnmatch(path, pattern):
            return True
        if path == pattern or path.startswith(pattern.rstrip("/") + "/"):
            return True
    return False


def scope_error(path: str, in_scope: list[str], out_scope: list[str]) -> str | None:
    if out_scope and _matches(path, out_scope):
        return f"文件属于禁止修改范围：{path}"
    if in_scope and not _matches(path, in_scope):
        return f"文件不在任务允许范围内：{path}"
    return None


def validate_generated_files(
    raw_files, current: dict[str, str], in_scope: list[str], out_scope: list[str]
) -> tuple[dict[str, str], str | None]:
    if not isinstance(raw_files, dict) or not raw_files:
        return {}, "模型没有产出文件"
    changes: dict[str, str] = {}
    total = 0
    for raw_path, content in raw_files.items():
        path = try_normalize_relpath(str(raw_path))
        if not path:
            continue
        if is_secret_path(path):
            return {}, f"拒绝写入密钥/凭据文件：{path}"
        error = scope_error(path, in_scope, out_scope)
        if error:
            return {}, error
        if not isinstance(content, str) or not content.strip():
            continue
        content = content[:MAX_TASK_CHARS]
        if path not in changes and len(changes) >= MAX_FILES_PER_TASK:
            return {}, f"单任务修改文件过多（最多 {MAX_FILES_PER_TASK} 个）"
        total += len(content)
        if total > MAX_TASK_CHARS:
            return {}, "单任务改动体积过大"
        changes[path] = content
    if not changes:
        return {}, "没有有效文件内容"
    try:
        assert_changes_preserve_tests(changes, current)
    except ValueError as exc:
        return {}, str(exc)
    return changes, None


def _spec_text(change: dict) -> str:
    return (
        f"标题：{change['title']}\n目标：{change['goal']}\n"
        f"In：{'; '.join(change['in_scope']) or '未指定'}\n"
        f"Out：{'; '.join(change['out_scope']) or '未指定'}\n"
        f"接口/契约：{'; '.join(change['interfaces']) or '未指定'}\n"
        f"验收：{'; '.join(change['acceptance_cases']) or '未指定'}\n"
        f"非功能：{'; '.join(change['nfr']) or '未指定'}"
    )


def _tree(paths: list[str], limit: int = 120) -> str:
    return "\n".join(sorted(paths)[:limit]) or "（空）"


async def _task_files(
    repo: dict, change: dict, task: dict, working: dict[str, str]
) -> tuple[str, str]:
    paths: list[str] = []
    for pattern in task.get("in_scope") or []:
        if pattern in working:
            paths.append(pattern)
        for path in working:
            if len(paths) >= MAX_CONTEXT_FILES:
                break
            if _matches(path, [pattern]) and path not in paths:
                paths.append(path)
    try:
        hits = await retrieve(
            f"{change['title']} {task['title']} {task['acceptance']}",
            top_k=6,
            repo_ids=[str(repo["id"])],
            user_id=int(change["user_id"]),
        )
    except Exception:  # noqa: BLE001
        hits = []
    for hit in hits:
        if hit.path in working and hit.path not in paths:
            paths.append(hit.path)
        if len(paths) >= MAX_CONTEXT_FILES:
            break
    for special in ("AGENTS.md", "CLAUDE.md"):
        if special in working and special not in paths:
            paths.insert(0, special)
    paths = paths[:MAX_CONTEXT_FILES]
    blocks = [f"--- {path} ---\n{working[path][:8000]}" for path in paths]
    return _tree(list(working)), "\n\n".join(blocks) or "（无相关文件）"


def _gate_failure(gate: dict) -> str:
    failed = [s for s in gate.get("steps", []) if s.get("status") == "failed"]
    if not failed:
        return (gate.get("stderr") or gate.get("stdout") or "验证失败")[:4000]
    parts = []
    for step in failed:
        parts.append(
            f"$ {step.get('command', '')}\n退出码 {step.get('exit_code')}\n"
            f"{(step.get('stdout') or '')[-1500:]}\n{(step.get('stderr') or '')[-800:]}"
        )
    return "\n\n".join(parts)[:6000]


def compact_gate(gate: dict) -> dict:
    steps = []
    for step in gate.get("steps", []):
        steps.append({
            "name": step.get("name"),
            "command": step.get("command"),
            "status": step.get("status"),
            "exit_code": step.get("exit_code"),
            "timed_out": step.get("timed_out"),
            "duration_ms": step.get("duration_ms"),
            "stdout": (step.get("stdout") or "")[-800:],
            "stderr": (step.get("stderr") or "")[-400:],
        })
    return {
        "status": gate.get("status"),
        "stack": gate.get("stack"),
        "notes": gate.get("notes") or [],
        "steps": steps,
        "exit_code": gate.get("exit_code"),
        "command": gate.get("command"),
        "image": gate.get("image"),
        "at": gate.get("at"),
        "elapsed_ms": gate.get("elapsed_ms"),
    }


async def _set_task(task_id: str, status: str, attempts: int, result: dict) -> None:
    await execute(
        "UPDATE change_tasks SET status = %s, attempts = %s, result = %s, "
        "updated_at = now() WHERE id = %s",
        (status, attempts, json.dumps(result, ensure_ascii=False), task_id),
    )


async def _load_user(user_id: int) -> dict:
    rows = await query("SELECT id, username, role FROM users WHERE id = %s", (user_id,))
    if not rows:
        raise RuntimeError("变更归属账号不存在")
    return {"id": rows[0][0], "username": rows[0][1], "role": rows[0][2]}


async def _fail(change_id: str, task_id: str | None, message: str) -> None:
    if task_id:
        await execute(
            "UPDATE change_tasks SET status = 'failed', updated_at = now() WHERE id = %s",
            (task_id,),
        )
    await service.set_change_status(change_id, "failed", message)


async def execute_change(change_id: str, user_id: int, ctx=None) -> dict:
    change = await service.get_change(change_id, user_id)
    if not change:
        raise RuntimeError("变更不存在")
    if change["status"] not in ("plan_approved", "failed", "executing"):
        raise RuntimeError("计划尚未批准，不能执行")
    tasks = change["tasks"]
    if not tasks:
        raise RuntimeError("没有可执行的任务")
    repo = await get_repo(change["repo_id"], user_id)
    if not repo:
        raise RuntimeError("仓库不存在")
    if repo["status"] != "ready":
        raise RuntimeError("仓库尚未完成索引")
    user = await _load_user(user_id)

    started = time.perf_counter()
    await service.set_change_status(change_id, "executing", error=None)
    await execute(
        "UPDATE change_tasks SET status = 'pending', attempts = 0, result = '{}'::jsonb, "
        "updated_at = now() WHERE request_id = %s",
        (change_id,),
    )

    initial = await _collect_repo_files(str(repo["id"]), user)
    if not initial:
        await _fail(change_id, None, "仓库没有可读文件")
        raise RuntimeError("仓库没有可读文件")
    working = dict(initial)
    changed_paths: set[str] = set()
    last_gate: dict = {"status": "unsupported", "steps": [], "notes": []}
    summaries: list[dict] = []
    template_hints = {
        kind: template_for(kind)["executor_hint"] for kind in
        ("feature", "bugfix", "refactor", "test", "docs", "contract")
    }

    for index, task in enumerate(tasks):
        if ctx:
            await ctx.check_cancel()
            await ctx.update(
                progress=min(0.85, 0.05 + 0.8 * index / max(1, len(tasks))),
                step=f"执行任务 {task['seq']}：{task['title']}",
            )
        await execute(
            "UPDATE change_tasks SET status = 'running', updated_at = now() WHERE id = %s",
            (task["id"],),
        )
        tree, files_block = await _task_files(repo, change, task, working)
        prompt = _TASK_PROMPT.format(
            spec=_spec_text(change),
            task_title=task["title"], task_kind=task["kind"],
            task_label=template_for(task["kind"])["label"],
            in_scope="; ".join(task["in_scope"]) or "（整个仓库）",
            out_scope="; ".join(task["out_scope"]) or "（无）",
            acceptance=task["acceptance"],
            template_hint=template_hints.get(task["kind"], ""),
            rules=_rules(repo), tree=tree, files=files_block,
            max_files=MAX_FILES_PER_TASK,
        )
        attempts = 0
        gate = last_gate
        notes = ""
        task_files: list[str] = []
        while True:
            if ctx:
                await ctx.check_cancel()
            await ensure_token_budget(user_id=user_id)
            data = await llm_json(prompt, user_id=user_id, source="change", purpose="plan")
            notes = str(data.get("notes") or "")[:2000]
            raw_files = data.get("files")
            if not raw_files and task["kind"] == "test":
                # Verification-only task: run the regression gate without
                # inventing a file change just to satisfy the executor.
                changes, error = {}, None
            else:
                changes, error = validate_generated_files(
                    raw_files, working, task["in_scope"], task["out_scope"]
                )
            if error:
                attempts += 1
                if attempts >= MAX_REPAIR_ATTEMPTS:
                    await _set_task(task["id"], "failed", attempts, {"error": error})
                    await _fail(change_id, task["id"], f"任务 {task['seq']} 未产出有效改动：{error}")
                    raise RuntimeError(error)
                prompt = _REPAIR_PROMPT.format(
                    task_title=task["title"], acceptance=task["acceptance"],
                    failure=error, files=files_block,
                )
                continue

            if changes:
                working.update(changes)
                changed_paths.update(changes)
                task_files = sorted(changes)
            gate = await run_verification(
                repo, user, overrides={p: working[p] for p in changed_paths}
            )
            last_gate = gate
            if gate["status"] == "failed":
                attempts += 1
                if attempts >= MAX_REPAIR_ATTEMPTS:
                    await _set_task(
                        task["id"], "failed", attempts,
                        {"error": "验证门失败", "gate": compact_gate(gate), "files": task_files},
                    )
                    await _fail(
                        change_id, task["id"],
                        f"任务 {task['seq']} 连续 {attempts} 次未通过验证门",
                    )
                    raise RuntimeError("验证门失败")
                files_block = "\n\n".join(
                    f"--- {path} ---\n{working[path][:8000]}" for path in task_files
                )
                prompt = _REPAIR_PROMPT.format(
                    task_title=task["title"], acceptance=task["acceptance"],
                    failure=_gate_failure(gate), files=files_block,
                )
                continue
            break

        result = {
            "notes": notes, "files": task_files,
            "gate": compact_gate(gate), "attempts": attempts,
            "tests": data.get("tests") or [],
        }
        await _set_task(task["id"], "ready", attempts, result)
        summaries.append({
            "seq": task["seq"], "title": task["title"], "kind": task["kind"],
            "files": task_files, "acceptance": task["acceptance"],
            "gate": gate["status"], "attempts": attempts,
        })

    final_changes = {
        path: working[path] for path in changed_paths
        if working.get(path) != initial.get(path)
    }
    if not final_changes:
        await _fail(change_id, None, "所有任务都没有产生实际文件改动")
        raise RuntimeError("没有产生实际文件改动")
    if len(final_changes) > 20 or sum(len(v) for v in final_changes.values()) > 300_000:
        await _fail(change_id, None, "最终提案超过单次应用上限（20 文件 / 300KB）")
        raise RuntimeError("最终提案超过单次应用上限")

    if ctx:
        await ctx.update(progress=0.9, step="生成统一提案")
    edit = await create_edit(
        user_id=user_id, session_id=None, repo_id=change["repo_id"],
        files=final_changes, note=f"变更 {change['title']}（v{change['version']}）",
        mode="ask",
    )
    evidence = {
        "summary": "全部任务已通过验证门" if last_gate["status"] == "passed"
        else "验证门不可用，改动未经真实验证",
        "spec": _spec_text(change),
        "tasks": summaries,
        "gate": compact_gate(last_gate),
        "unverified": [] if last_gate["status"] == "passed" else ["验证门未通过或当前技术栈不支持"],
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
    }
    try:
        review = await review_diff(
            user_id=user_id,
            repo=repo,
            diff=edit["diff"],
            files=final_changes,
            title=f"变更 {change['title']}（v{change['version']}）",
            evidence={"gate": compact_gate(last_gate), "tasks": summaries},
            spec=_spec_text(change),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("change_review_failed", change_id=change_id, error=str(exc))
        review = {
            "verdict": "warn", "summary": f"只读审查失败：{exc}",
            "blocking": [], "non_blocking": [], "evidence": [],
        }

    proposal = {
        "edit_id": edit["id"], "diff": edit["diff"],
        "files": sorted(final_changes), "gate": compact_gate(last_gate),
        "review": review, "tasks": summaries,
    }
    await service.set_proposal(change_id, proposal)
    await service.set_evidence(change_id, evidence)
    await service.set_change_status(change_id, "review", error=None)
    if ctx:
        await ctx.update(progress=0.98, step="等待人工审批")
    return {
        "change_id": change_id, "edit_id": edit["id"],
        "files": sorted(final_changes), "gate": last_gate["status"],
        "review": review.get("verdict"),
    }


def _rules(repo: dict) -> str:
    from app.core.agent.rules import load_repo_rules
    rules = load_repo_rules([repo])
    return "\n\n".join(rule["content"] for rule in rules)[:4000] or "（无）"

"""Red-Green task engine.

Pipeline (deterministic, LLM used only where it adds value):
  locate relevant files → LLM returns {analysis, test_files, fix_files}
  → run tests in the sandbox WITHOUT the fix (must be red)
  → run tests WITH the fix (must be green)
  → store a unified diff; the user approves before anything touches the repo.
"""
import difflib
import json
import re
import shlex
import time
from pathlib import Path

import structlog

from app.config import settings
from app.core.conflicts import ConflictError
from app.core.indexing.pipeline import get_repo
from app.core.llm.json_call import llm_json
from app.core.rag.retriever import retrieve
from app.core.sandbox.runtime import deps_volume_name, execute as sandbox_execute, sandbox_status
from app.core.security.audit import AuditAction, log_audit
from app.core.security.limits import check_sandbox_quota, ensure_token_budget
from app.core.security.paths import (
    UnsafePathError, is_secret_path, resolve_repo_path, try_normalize_relpath,
)
from app.core.security.test_guard import (
    assert_changes_preserve_tests, assert_new_test_files,
)
from app.db import execute, query

logger = structlog.get_logger()

MAX_CONTEXT_FILES = 3
MAX_CONTEXT_TEST_FILES = 1
MAX_FILE_CHARS = 8000
MAX_TOTAL_CHARS = 20000
MAX_TREE_PATHS = 60
MAX_REPAIR_ATTEMPTS = 3

_PROMPT = """你是一名修复工程师，需要在一个真实仓库里复现并修复一个 bug。

仓库：{repo_name}
唯一顶层目录：{root_prefix}（测试命令会在该目录下执行；没有则为仓库根目录）
Bug 描述：
{bug_report}

仓库文件（最多 {tree_count} 个）：
{tree}

相关源码：
{files}

请完成：
1. 写一个 pytest 测试文件，稳定复现该 bug（修复前失败、修复后通过）。测试文件必须是新文件。
2. 给出修复后的完整文件内容（只包含需要修改的文件，保留其余代码不变）。
3. 分析根因（简洁）。

只输出 JSON（不要 markdown 代码块），结构：
{{"analysis": "根因分析", "test_files": {{"路径": "完整文件内容"}}, "fix_files": {{"路径": "修复后的完整文件内容"}}}}

要求：
- 路径与上面给出的仓库文件路径保持一致（包含顶层目录前缀）。
- 测试里 import 使用去掉顶层目录后的包路径（与仓库现有测试保持一致）。
- 不要修改或覆盖已有测试文件，测试写成新文件。
- 不确定时选择最小改动。"""


async def _update_task(task_id: str, status: str | None = None, result: dict | None = None) -> None:
    sets, params = ["updated_at = now()"], []
    if status:
        sets.append("status = %s")
        params.append(status)
    if result is not None:
        sets.append("result = %s")
        params.append(json.dumps(result, ensure_ascii=False))
    await execute(f"UPDATE tasks SET {', '.join(sets)} WHERE id = %s", (*params, task_id))


async def _append_step(task_id: str, step: dict) -> None:
    rows = await query("SELECT steps FROM tasks WHERE id = %s", (task_id,))
    steps = rows[0][0] if rows and isinstance(rows[0][0], list) else []
    steps.append(step)
    await execute(
        "UPDATE tasks SET steps = %s, updated_at = now() WHERE id = %s",
        (json.dumps(steps, ensure_ascii=False), task_id),
    )


def _common_root(paths: list[str]) -> str | None:
    if not paths:
        return None
    tops = {p.split("/")[0] for p in paths}
    if len(tops) == 1:
        top = tops.pop()
        if any("/" in p for p in paths) and not any(p == top for p in paths):
            return top
    return None


def _pytest_command(test_paths: list[str], root_prefix: str | None) -> str:
    paths = list(test_paths)
    prefix = ""
    if root_prefix:
        stripped = [p[len(root_prefix) + 1:] if p.startswith(root_prefix + "/") else p for p in paths]
        paths = stripped
        prefix = f"cd {shlex.quote(root_prefix)} && "
    return prefix + "python -m pytest -q " + " ".join(shlex.quote(p) for p in paths)


def _full_suite_command(root_prefix: str | None) -> str:
    prefix = f"cd {shlex.quote(root_prefix)} && " if root_prefix else ""
    return prefix + "python -m compileall -q . && python -m pytest -q"


def _classify_red(result: dict) -> tuple[bool, str]:
    """A red phase only counts when the test actually ran and failed."""
    if result.get("timed_out"):
        return False, "复现测试超时，不能证明 bug 已复现"
    if result.get("exit_code") == 0:
        return False, "测试没有失败，可能未复现该 bug"
    text = f"{result.get('stdout') or ''}\n{result.get('stderr') or ''}".lower()
    invalid_markers = (
        "error collecting",
        "errors during collection",
        "collected 0 items",
        "no tests ran",
        "modulenotfounderror",
        "importerror",
        "syntaxerror",
    )
    for marker in invalid_markers:
        if marker in text:
            return False, f"复现测试未能有效运行（{marker}），不能证明 bug 已复现"
    return True, "测试按预期失败（红）"


def _snapshot_file(root: Path, rel: str) -> str | None:
    try:
        target = resolve_repo_path(root, rel)
    except UnsafePathError:
        return None
    if not target.is_file():
        return None
    try:
        return target.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _read_repo_file(root: Path, rel: str) -> str:
    try:
        target = resolve_repo_path(root, rel)
    except UnsafePathError:
        return ""
    if not target.is_file():
        return ""
    try:
        return target.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


async def _collect_context(repo: dict, bug_report: str) -> tuple[dict[str, str], list[str], str | None]:
    """Pick files likely involved in the bug, bounded in size."""
    root = Path(repo["root_path"])
    rows = await query(
        "SELECT path FROM repo_files WHERE repo_id = %s ORDER BY path", (repo["id"],)
    )
    all_paths = [r[0] for r in rows]
    tree = all_paths[:MAX_TREE_PATHS]
    root_prefix = _common_root(all_paths)

    selected: list[str] = []
    try:
        hits = await retrieve(bug_report, top_k=8, repo_ids=[repo["id"]])
        selected = [h.path for h in hits if h.path]
    except Exception as exc:  # noqa: BLE001
        logger.warning("task_retrieval_failed", error=str(exc))

    if not selected:
        selected = [p for p in all_paths if not p.startswith(("tests/", "test/"))][:MAX_CONTEXT_FILES]

    tests = [p for p in all_paths if "/test" in p or p.startswith("test")]
    files: dict[str, str] = {}
    total = 0
    for path in selected:
        if len(files) >= MAX_CONTEXT_FILES or path in files:
            continue
        content = _read_repo_file(root, path)
        if not content or total + len(content) > MAX_TOTAL_CHARS:
            continue
        files[path] = content[:MAX_FILE_CHARS]
        total += len(content)

    existing_tests = 0
    for path in tests:
        if existing_tests >= MAX_CONTEXT_TEST_FILES or path in files:
            continue
        content = _read_repo_file(root, path)
        if not content:
            continue
        files[path] = content[:4000]
        existing_tests += 1

    return files, tree, root_prefix


def _build_diff(root: Path, fix_files: dict[str, str], test_files: dict[str, str]) -> str:
    parts: list[str] = []
    for path, new_content in {**fix_files, **test_files}.items():
        old_content = _read_repo_file(root, path)
        old_label = f"a/{path}" if old_content else "/dev/null"
        diff = difflib.unified_diff(
            old_content.splitlines(),
            new_content.splitlines(),
            fromfile=old_label,
            tofile=f"b/{path}",
            lineterm="",
        )
        parts.append("\n".join(diff))
    return "\n\n".join(p for p in parts if p.strip())


def _validate_files(files: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    for path, content in (files or {}).items():
        rel = try_normalize_relpath(path)
        if not rel or is_secret_path(rel):
            continue
        if not isinstance(content, str) or not content.strip():
            continue
        out[rel] = content
    return out


async def _sandbox_run(
    task_id: str, user: dict, repo_id: str,
    repo_files: dict[str, str], extra: dict[str, str], command: str,
    ctx=None,
) -> dict:
    if ctx:
        await ctx.check_cancel()
        await ctx.update(step="沙箱验证")
    try:
        await check_sandbox_quota(user)
    except Exception as exc:  # HTTPException or other quota errors
        detail = getattr(exc, "detail", str(exc))
        raise RuntimeError(f"沙箱配额不足：{detail}")

    status = await sandbox_status()
    image = settings.sandbox_builder_image if status.get("builder_available") else settings.sandbox_image
    result = await sandbox_execute(
        files={**repo_files, **extra},
        command=command,
        timeout=max(settings.sandbox_timeout, 120),
        image=image,
        deps_volume=deps_volume_name(str(repo_id)),
        job_id=ctx.job_id if ctx else None,
    )
    if ctx:
        await ctx.check_cancel()
    await log_audit(
        AuditAction.SANDBOX_RUN,
        user_id=str(user.get("id", "")),
        details={"task_id": task_id, "command": command, "exit_code": result.get("exit_code")},
    )
    return result


async def run_task(task_id: str, ctx=None) -> None:
    """Background entrypoint for one red-green task."""
    started = time.perf_counter()
    if ctx:
        await ctx.check_cancel()
        await ctx.update(progress=0.02, step="加载任务")
    rows = await query(
        "SELECT t.id, t.user_id, t.repo_id, t.bug_report, r.root_path, r.name, r.status "
        "FROM tasks t JOIN repos r ON r.id = t.repo_id WHERE t.id = %s",
        (task_id,),
    )
    if not rows:
        return
    _, user_id, repo_id, bug_report, root_path, repo_name, repo_status = rows[0]

    result: dict = {}
    try:
        if repo_status != "ready":
            raise RuntimeError("仓库尚未完成索引，无法执行任务")
        status = await sandbox_status()
        if not status["available"]:
            raise RuntimeError(f"沙箱不可用：{status['reason']}")

        user_rows = await query("SELECT id, username, role FROM users WHERE id = %s", (user_id,))
        if not user_rows:
            raise RuntimeError("任务归属账号不存在")
        user = {"id": user_rows[0][0], "username": user_rows[0][1], "role": user_rows[0][2]}
        repo = {"id": str(repo_id), "root_path": root_path, "name": repo_name}
        root = Path(root_path)

        await _append_step(task_id, {"step": "locate", "status": "running"})
        files, tree, root_prefix = await _collect_context(repo, bug_report)
        if ctx:
            await ctx.check_cancel()
            await ctx.update(progress=0.12, step="定位相关代码")

        await _append_step(task_id, {
            "step": "locate", "status": "done",
            "files": list(files.keys()), "root_prefix": root_prefix,
        })

        from app.core.tools.run_code import _collect_repo_files
        repo_files = await _collect_repo_files(str(repo_id), user)

        prompt = _PROMPT.format(
            repo_name=repo_name,
            root_prefix=root_prefix or "（无）",
            bug_report=bug_report[:4000],
            tree_count=len(tree),
            tree="\n".join(tree),
            files="\n\n".join(f"--- {p} ---\n{c}" for p, c in files.items()),
        )
        await _append_step(task_id, {"step": "analyze", "status": "running"})
        await ensure_token_budget(user)
        if ctx:
            await ctx.check_cancel()
            await ctx.update(progress=0.22, step="生成复现测试与修复")
        data = await llm_json(prompt, user_id=user["id"], source="task")
        if ctx:
            await ctx.check_cancel()
            await ctx.update(progress=0.32, step="准备红阶段")
        analysis = str(data.get("analysis", ""))[:2000]
        test_files = _validate_files(data.get("test_files") or {})
        fix_files = _validate_files(data.get("fix_files") or {})
        if not test_files:
            raise RuntimeError("模型没有产出复现测试")
        if not fix_files:
            raise RuntimeError("模型没有产出修复文件")
        await _append_step(task_id, {
            "step": "analyze", "status": "done", "analysis": analysis,
            "test_files": list(test_files.keys()), "fix_files": list(fix_files.keys()),
        })

        # red: tests must fail without the fix
        red_command = _pytest_command(list(test_files.keys()), root_prefix)
        await _append_step(task_id, {"step": "red", "status": "running", "command": red_command})
        red = await _sandbox_run(task_id, user, str(repo_id), repo_files, test_files, red_command, ctx=ctx)
        red_ok, red_detail = _classify_red(red)
        await _append_step(task_id, {
            "step": "red", "status": "done" if red_ok else "warn",
            "exit_code": red.get("exit_code"), "detail": red_detail,
        })
        if not red_ok:
            raise RuntimeError(f"{red_detail}。请补充更具体的复现步骤或检查测试依赖。")

        # green: the full suite must pass, not just the new reproduction test
        green_command = _full_suite_command(root_prefix)
        await _append_step(task_id, {"step": "green", "status": "running"})
        green = await _sandbox_run(task_id, user, str(repo_id), repo_files, {**test_files, **fix_files}, green_command, ctx=ctx)

        attempt = 0
        while green.get("exit_code") != 0 and attempt < MAX_REPAIR_ATTEMPTS:
            attempt += 1
            if ctx:
                await ctx.check_cancel()
                await ctx.update(progress=min(0.85, 0.4 + 0.15 * attempt), step=f"修复第 {attempt} 次")
            repair_prompt = (
                f"修复后全量测试仍然失败（第 {attempt}/{MAX_REPAIR_ATTEMPTS} 次修复）。"
                "请根据以下真实输出修正 fix_files，只输出同样的 JSON 结构。\n"
                f"测试输出：\n{(green.get('stdout') or '')[-4000:]}\n{(green.get('stderr') or '')[-2000:]}\n"
                f"当前 fix_files：{json.dumps(fix_files, ensure_ascii=False)[:8000]}"
            )
            await ensure_token_budget(user)
            data2 = await llm_json(repair_prompt, user_id=user["id"], source="task")
            fix_files = _validate_files(data2.get("fix_files") or fix_files) or fix_files
            green = await _sandbox_run(task_id, user, str(repo_id), repo_files, {**test_files, **fix_files}, green_command, ctx=ctx)

        green_ok = green.get("exit_code") == 0
        await _append_step(task_id, {
            "step": "green", "status": "done" if green_ok else "failed",
            "exit_code": green.get("exit_code"),
            "detail": (
                f"全量测试通过（绿，修复 {attempt} 次）" if green_ok
                else f"修复 {attempt} 次后全量测试仍失败"
            ),
        })

        base_files = {path: _snapshot_file(root, path) for path in fix_files}
        if not green_ok:
            result = {
                "analysis": analysis, "root_prefix": root_prefix,
                "test_files": test_files, "fix_files": fix_files,
                "base_files": base_files,
                "red": red, "green": green,
                "repair_attempts": attempt,
                "diff": _build_diff(root, fix_files, test_files),
                "applied": False,
            }
            await _update_task(task_id, "failed", result)
            return

        result = {
            "analysis": analysis,
            "root_prefix": root_prefix,
            "test_files": test_files,
            "fix_files": fix_files,
            "base_files": base_files,
            "repair_attempts": attempt,
            "red": {"exit_code": red.get("exit_code"), "stdout": (red.get("stdout") or "")[-3000:],
                    "stderr": (red.get("stderr") or "")[-1500:], "command": red_command,
                    "detail": red_detail},
            "green": {"exit_code": green.get("exit_code"), "stdout": (green.get("stdout") or "")[-3000:],
                      "stderr": (green.get("stderr") or "")[-1500:], "command": green_command},
            "diff": _build_diff(root, fix_files, test_files),
            "applied": False,
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
        }
        await _update_task(task_id, "ready", result)
        if ctx:
            await ctx.update(progress=0.95, step="等待人工审批")
        logger.info("task_ready", task_id=task_id, test_files=len(test_files), fix_files=len(fix_files))
    except Exception as exc:  # noqa: BLE001
        from app.core.jobs.models import JobCanceled
        if isinstance(exc, JobCanceled):
            logger.info("task_canceled", task_id=task_id)
            await _append_step(task_id, {"step": "canceled", "status": "done", "detail": "用户取消"})
            await _update_task(task_id, "canceled", result or {"error": "用户取消"})
            raise
        logger.exception("task_failed", task_id=task_id)
        detail = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
        if isinstance(exc, TimeoutError):
            detail = f"模型生成超时（{settings.task_llm_timeout}s），请缩小 bug 范围或重试"
        await _append_step(task_id, {"step": "error", "status": "failed", "detail": detail[:1000]})
        await _update_task(task_id, "failed", result or {"error": detail[:1000]})


async def apply_task_result(task: dict) -> list[str]:
    """Write the approved files into the repo workspace. Returns applied paths."""
    repo = await get_repo(task["repo_id"], task["user_id"])
    if not repo:
        raise RuntimeError("仓库不存在")
    root = Path(repo["root_path"]).resolve()
    result = task["result"] or {}
    raw_files = {**result.get("fix_files", {}), **result.get("test_files", {})}
    if not raw_files:
        raise RuntimeError("没有可应用的文件")

    changes: dict[str, str] = {}
    for rel, content in raw_files.items():
        path = try_normalize_relpath(rel)
        if path and is_secret_path(path):
            raise RuntimeError(f"拒绝写入密钥/凭据文件：{path}")
        if not path or not isinstance(content, str) or not content.strip():
            continue
        changes[path] = content
    if not changes:
        raise RuntimeError("模型产出的文件路径均不合法")

    for rel, expected in (result.get("base_files") or {}).items():
        path = try_normalize_relpath(rel)
        if not path:
            continue
        target = resolve_repo_path(root, path)
        current = target.read_text(encoding="utf-8", errors="replace") if target.is_file() else None
        if current != expected:
            raise ConflictError(f"文件在任务生成后已被修改：{path}，请重新创建任务")

    declared_tests = {
        p for p in (try_normalize_relpath(k) for k in result.get("test_files", {})) if p
    }
    test_files = {
        path: content for path, content in changes.items() if path in declared_tests
    }
    base: dict[str, str | None] = {}
    for path in changes:
        target = resolve_repo_path(root, path)
        base[path] = target.read_text(encoding="utf-8", errors="replace") if target.is_file() else None

    assert_new_test_files(test_files, base)
    assert_changes_preserve_tests(changes, base)

    applied: list[str] = []
    for rel, content in changes.items():
        target = resolve_repo_path(root, rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        applied.append(rel)

    result["applied"] = True
    await _update_task(task["id"], "applied", result)
    from app.core.git_ops.service import auto_commit
    await auto_commit(root, f"task: apply {str(task['id'])[:8]}")
    return applied
"""Read-only reviewer.

The reviewer is a direct LLM call with no tools, so it cannot edit files or
run commands. It returns a structured verdict plus evidence for the UI.
"""
import json
from datetime import datetime, timezone

from app.core.agent.rules import load_repo_rules
from app.core.llm.json_call import llm_json
from app.core.security.limits import ensure_token_budget
from app.db import execute, query

MAX_DIFF_CHARS = 20_000
MAX_FILE_CHARS = 6_000
MAX_FILES = 3
MAX_RULES_CHARS = 4_000

_PROMPT = """你是一名只读代码审查员。你不能修改文件，也不能执行命令；你的任务是判断这份改动是否可以安全交付。

项目：{repo_name}
审查对象：{title}

SPEC / 验收标准：
{spec}

项目约定（AGENTS.md / 项目规则）：
{rules}

改动 diff：
```diff
{diff}
```

改动后的文件内容（最多 {file_count} 个，已截断）：
{files}

现有验证证据：
{evidence}

请只输出 JSON（不要 markdown 代码块）：
{{
  "verdict": "pass | warn | block",
  "summary": "一句话结论",
  "blocking": [{{"file": "路径", "line": 1, "issue": "必须修复的问题", "suggestion": "建议"}}],
  "non_blocking": [{{"file": "路径", "line": 1, "issue": "可选改进", "suggestion": "建议"}}],
  "evidence": ["你依据的 diff 行、测试结果或项目约定"]
}}

审查重点：
- 正确性、安全漏洞、越权改动、被删除或跳过的测试
- 是否满足项目约定；是否引入前端/后端契约漂移
- 缺少验证时明确写进 blocking 或 evidence，不要假设已通过
- 不要提出大范围重写；blocking 只放真正会导致交付失败的问题"""


def _clean_items(items: object, limit: int = 10) -> list[dict]:
    out: list[dict] = []
    for item in items if isinstance(items, list) else []:
        if isinstance(item, str):
            issue = item.strip()[:500]
            if issue:
                out.append({"issue": issue})
        elif isinstance(item, dict):
            issue = str(item.get("issue") or item.get("message") or "").strip()[:500]
            if not issue:
                continue
            entry = {
                "issue": issue,
                "file": str(item.get("file") or "")[:200],
                "suggestion": str(item.get("suggestion") or "")[:500],
            }
            try:
                line = int(item.get("line"))
                if line > 0:
                    entry["line"] = line
            except (TypeError, ValueError):
                pass
            out.append(entry)
        if len(out) >= limit:
            break
    return out


def clean_review(data: dict) -> dict:
    verdict = str(data.get("verdict") or "").lower()
    if verdict not in ("pass", "warn", "block"):
        verdict = "warn"
    evidence = data.get("evidence")
    return {
        "verdict": verdict,
        "summary": str(data.get("summary") or "")[:1500],
        "blocking": _clean_items(data.get("blocking")),
        "non_blocking": _clean_items(data.get("non_blocking")),
        "evidence": [str(e)[:500] for e in evidence[:10]] if isinstance(evidence, list) else [],
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
    }


async def review_diff(
    *,
    user_id: int,
    repo: dict,
    diff: str,
    files: dict[str, str],
    title: str = "",
    evidence: dict | None = None,
    spec: str = "",
) -> dict:
    await ensure_token_budget(user_id=user_id)
    rules = load_repo_rules([repo])
    rules_text = "\n\n".join(
        f"[{rule['repo']} · {rule['source']}]\n{rule['content']}" for rule in rules
    )[:MAX_RULES_CHARS] or "（未提供）"
    selected = list(files.items())[:MAX_FILES]
    file_blocks = "\n\n".join(
        f"--- {path} ---\n{content[:MAX_FILE_CHARS]}" for path, content in selected
    ) or "（无文件内容）"
    if len(files) > MAX_FILES:
        file_blocks += f"\n\n（另有 {len(files) - MAX_FILES} 个文件未展开，请以 diff 为准）"

    prompt = _PROMPT.format(
        repo_name=repo.get("name") or "仓库",
        title=title or "代码改动",
        spec=(spec or "（未提供）")[:6000],
        rules=rules_text,
        diff=(diff or "")[:MAX_DIFF_CHARS],
        file_count=len(selected),
        files=file_blocks,
        evidence=json.dumps(evidence or {"note": "未提供额外验证"}, ensure_ascii=False)[:3000],
    )
    data = await llm_json(prompt, user_id=user_id, source="review")
    return clean_review(data)


async def review_edit(edit_id: str, user_id: int) -> dict:
    rows = await query(
        """
        SELECT e.files, e.diff, r.name, r.root_path, COALESCE(r.rules, '')
        FROM edits e JOIN repos r ON r.id = e.repo_id
        WHERE e.id = %s AND e.user_id = %s
        """,
        (edit_id, user_id),
    )
    if not rows:
        raise ValueError("修改不存在")
    files, diff, repo_name, root_path, rules = rows[0]
    review = await review_diff(
        user_id=user_id,
        repo={"name": repo_name, "root_path": root_path, "rules": rules},
        diff=diff or "",
        files=files or {},
        title=f"对话内编辑提案 {edit_id[:8]}",
    )
    await execute(
        "UPDATE edits SET review = %s WHERE id = %s AND user_id = %s",
        (json.dumps(review, ensure_ascii=False), edit_id, user_id),
    )
    return review


async def review_task(task: dict) -> dict:
    result = task.get("result") or {}
    evidence = {
        "red": (result.get("red") or {}).get("exit_code"),
        "green": (result.get("green") or {}).get("exit_code"),
        "green_command": (result.get("green") or {}).get("command"),
        "repair_attempts": result.get("repair_attempts"),
        "red_detail": (result.get("red") or {}).get("detail"),
        "green_tail": ((result.get("green") or {}).get("stdout") or "")[-1500:],
    }
    repo = await query(
        "SELECT name, root_path, COALESCE(rules, '') FROM repos WHERE id = %s",
        (task["repo_id"],),
    )
    repo_meta = (
        {"name": repo[0][0], "root_path": repo[0][1], "rules": repo[0][2]}
        if repo else {"name": task.get("repo_name") or "仓库"}
    )
    review = await review_diff(
        user_id=int(task["user_id"]),
        repo=repo_meta,
        diff=str(result.get("diff") or ""),
        files={**result.get("fix_files", {}), **result.get("test_files", {})},
        title=task.get("title") or "红绿修复任务",
        evidence=evidence,
    )
    result["review"] = review
    await execute(
        "UPDATE tasks SET result = %s, updated_at = now() WHERE id = %s AND user_id = %s",
        (json.dumps(result, ensure_ascii=False), task["id"], task["user_id"]),
    )
    return review

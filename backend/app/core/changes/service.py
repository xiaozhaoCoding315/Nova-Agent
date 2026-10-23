"""Change workflow domain: SPEC drafting, freezing, planning and queries."""
import json
import uuid

import structlog

from app.core.changes.templates import TEMPLATES
from app.core.indexing.pipeline import get_repo
from app.core.llm.json_call import llm_json
from app.core.rag.retriever import retrieve
from app.core.security.audit import AuditAction, log_audit
from app.core.security.limits import ensure_token_budget
from app.core.security.paths import try_normalize_relpath
from app.db import execute, query

logger = structlog.get_logger()

SPEC_STATUSES = (
    "drafting", "draft", "approved", "planning", "plan_ready", "plan_approved",
    "executing", "review", "applied", "rejected", "failed", "canceled",
)

MAX_LIST_ITEMS = 20
MAX_ITEM_CHARS = 500
MAX_TASKS = 8

_SPEC_PROMPT = """你是全栈开发 Agent 的需求分析师。请把用户需求整理成一份可确认的 SPEC。

用户需求：
{requirements}

项目：{repo_name}
项目文件（节选）：
{tree}

相关代码片段：
{context}

只输出 JSON（不要 markdown）：
{{
  "title": "不超过 40 字的变更标题",
  "goal": "目标与用户价值，2-4 句",
  "in_scope": ["本次要做的事/文件范围"],
  "out_scope": ["明确不做的事"],
  "interfaces": ["受影响的 API / 数据结构 / 前后端契约"],
  "acceptance_cases": ["可判定的验收用例，尽量带命令或测试名"],
  "nfr": ["性能/兼容/安全等非功能要求"],
  "open_questions": ["必须由用户澄清的歧义；没有则返回空数组"]
}}

要求：范围要具体；验收用例必须可判定；不要编造仓库中不存在的文件。"""

_PLAN_PROMPT = """你是全栈开发 Agent 的任务规划器。请把已冻结的 SPEC 拆成可独立验收的任务。

SPEC：
标题：{title}
目标：{goal}
范围 In：{in_scope}
范围 Out：{out_scope}
接口/契约：{interfaces}
验收用例：{acceptance_cases}
非功能要求：{nfr}

项目文件（节选）：
{tree}

相关代码片段：
{context}

项目约定：
{rules}

任务模板：
{templates}

只输出 JSON（不要 markdown）：
{{
  "summary": "计划摘要",
  "tasks": [
    {{
      "title": "任务标题",
      "kind": "feature|bugfix|refactor|test|docs|contract",
      "in_scope": ["允许修改的路径或路径前缀"],
      "out_scope": ["禁止修改的路径"],
      "acceptance": "可判定验收：命令/测试名 + 期望结果",
      "depends_on": [1]
    }}
  ]
}}

规则：
- 2-8 个任务；默认串行，depends_on 只能引用前面的任务序号。
- 每个任务必须有至少一条可判定验收。
- 写操作范围要具体；不要规划无关重构。
- 需要新增行为时，同时规划测试。"""


def _clean_items(items, limit: int = MAX_LIST_ITEMS) -> list[str]:
    out: list[str] = []
    for item in items if isinstance(items, list) else []:
        text = str(item or "").strip()
        if text:
            out.append(text[:MAX_ITEM_CHARS])
        if len(out) >= limit:
            break
    return out


def clean_spec(data: dict, fallback_title: str = "变更") -> dict:
    return {
        "title": (str(data.get("title") or fallback_title).strip()[:120] or fallback_title),
        "goal": str(data.get("goal") or "").strip()[:4000],
        "in_scope": _clean_items(data.get("in_scope")),
        "out_scope": _clean_items(data.get("out_scope")),
        "interfaces": _clean_items(data.get("interfaces")),
        "acceptance_cases": _clean_items(data.get("acceptance_cases")),
        "nfr": _clean_items(data.get("nfr")),
        "open_questions": _clean_items(data.get("open_questions")),
    }


async def _repo_context(repo: dict, query_text: str) -> tuple[str, str]:
    rows = await query(
        "SELECT path FROM repo_files WHERE repo_id = %s ORDER BY path LIMIT 120",
        (repo["id"],),
    )
    tree = "\n".join(r[0] for r in rows) or "（仓库尚未索引）"
    try:
        hits = await retrieve(query_text, top_k=6, repo_ids=[str(repo["id"])])
    except Exception:  # noqa: BLE001
        hits = []
    blocks = []
    for hit in hits:
        blocks.append(f"[{hit.path}:{hit.line_start}-{hit.line_end}]\n{hit.content[:1500]}")
    return tree, "\n\n".join(blocks) or "（无相关片段）"


async def create_change(user_id: int, repo_id: str, requirements: str, title: str | None) -> dict:
    repo = await get_repo(repo_id, user_id)
    if not repo:
        raise ValueError("仓库不存在或无权访问")
    change_id = str(uuid.uuid4())
    await execute(
        "INSERT INTO change_requests (id, user_id, repo_id, title, requirements, goal, status) "
        "VALUES (%s, %s, %s, %s, %s, %s, 'drafting')",
        (change_id, user_id, repo_id, (title or "变更")[:120], requirements[:8000], requirements[:4000]),
    )
    await log_audit(
        AuditAction.CHANGE_CREATED,
        user_id=str(user_id),
        details={"change_id": change_id, "repo_id": repo_id},
    )
    return await get_change(change_id, user_id)


async def draft_spec(change_id: str, ctx=None) -> dict:
    change = await _load_raw(change_id)
    if not change:
        raise ValueError("变更不存在")
    repo = await get_repo(str(change["repo_id"]), change["user_id"])
    if not repo:
        raise ValueError("仓库不存在")
    await _set_status(change_id, "drafting", error=None)
    await ensure_token_budget(user_id=change["user_id"])
    tree, context = await _repo_context(repo, change["requirements"])
    if ctx:
        await ctx.check_cancel()
        await ctx.update(progress=0.2, step="起草 SPEC")
    data = await llm_json(
        _SPEC_PROMPT.format(
            requirements=change["requirements"], repo_name=repo["name"],
            tree=tree[:6000], context=context[:12000],
        ),
        user_id=change["user_id"],
        source="change",
    )
    spec = clean_spec(data, fallback_title=change["title"])
    await execute(
        "UPDATE change_requests SET title = %s, goal = %s, in_scope = %s, out_scope = %s, "
        "interfaces = %s, acceptance_cases = %s, nfr = %s, open_questions = %s, "
        "status = 'draft', error = NULL, updated_at = now() WHERE id = %s",
        (
            spec["title"], spec["goal"],
            json.dumps(spec["in_scope"], ensure_ascii=False),
            json.dumps(spec["out_scope"], ensure_ascii=False),
            json.dumps(spec["interfaces"], ensure_ascii=False),
            json.dumps(spec["acceptance_cases"], ensure_ascii=False),
            json.dumps(spec["nfr"], ensure_ascii=False),
            json.dumps(spec["open_questions"], ensure_ascii=False),
            change_id,
        ),
    )
    return await get_change(change_id, change["user_id"])


async def update_spec(change_id: str, user_id: int, patch: dict) -> dict:
    change = await get_change(change_id, user_id)
    if not change:
        raise ValueError("变更不存在")
    if change["status"] not in ("draft", "failed"):
        raise ValueError("只有草稿状态可以编辑 SPEC")
    sets = []
    params: list = []
    for key in ("title", "goal"):
        if patch.get(key) is not None:
            sets.append(f"{key} = %s")
            params.append(str(patch[key])[:4000])
    for key in ("in_scope", "out_scope", "interfaces", "acceptance_cases", "nfr", "open_questions"):
        if patch.get(key) is not None:
            sets.append(f"{key} = %s")
            params.append(json.dumps(_clean_items(patch[key]), ensure_ascii=False))
    if not sets:
        return change
    sets.append("updated_at = now()")
    params.append(change_id)
    await execute(f"UPDATE change_requests SET {', '.join(sets)} WHERE id = %s", tuple(params))
    return await get_change(change_id, user_id)


async def approve_spec(change_id: str, user_id: int) -> dict:
    change = await get_change(change_id, user_id)
    if not change:
        raise ValueError("变更不存在")
    if change["status"] not in ("draft", "failed"):
        raise ValueError("当前状态不能冻结 SPEC")
    if not change["goal"].strip():
        raise ValueError("SPEC 缺少目标")
    if not change["acceptance_cases"]:
        raise ValueError("至少需要一条可判定验收用例")
    if change["open_questions"]:
        raise ValueError("仍有待澄清问题，请先编辑 SPEC 清空 open_questions")
    await execute(
        "UPDATE change_requests SET status = 'approved', version = version + 1, "
        "approved_at = now(), updated_at = now(), error = NULL WHERE id = %s",
        (change_id,),
    )
    return await get_change(change_id, user_id)


async def generate_plan(change_id: str, ctx=None) -> dict:
    raw = await _load_raw(change_id)
    if not raw:
        raise ValueError("变更不存在")
    user_id = raw["user_id"]
    change = await get_change(change_id, user_id)
    if not change:
        raise ValueError("变更不存在")
    if change["status"] not in ("approved", "planning", "failed"):
        raise ValueError("请先冻结 SPEC")
    repo = await get_repo(str(change["repo_id"]), user_id)
    if not repo:
        raise ValueError("仓库不存在")
    await _set_status(change_id, "planning", error=None)
    await ensure_token_budget(user_id=user_id)
    tree, context = await _repo_context(repo, f"{change['title']} {change['goal']}")
    if ctx:
        await ctx.check_cancel()
        await ctx.update(progress=0.2, step="规划任务")
    prompt = _PLAN_PROMPT.format(
        title=change["title"], goal=change["goal"],
        in_scope="; ".join(change["in_scope"]) or "（未指定）",
        out_scope="; ".join(change["out_scope"]) or "（未指定）",
        interfaces="; ".join(change["interfaces"]) or "（未指定）",
        acceptance_cases="; ".join(change["acceptance_cases"]) or "（未指定）",
        nfr="; ".join(change["nfr"]) or "（未指定）",
        tree=tree[:6000], context=context[:12000],
        rules=_rules_text(repo),
        templates="\n".join(
            f"- {kind}: {meta['planner_hint']}" for kind, meta in TEMPLATES.items()
        ),
    )
    data = await llm_json(prompt, user_id=user_id, source="change")
    tasks, error = validate_plan(data)
    if error:
        await _set_status(change_id, "failed", error=error)
        raise ValueError(error)
    if ctx:
        await ctx.update(progress=0.7, step="保存计划")
    await execute("DELETE FROM change_tasks WHERE request_id = %s", (change_id,))
    for seq, task in enumerate(tasks, 1):
        await execute(
            "INSERT INTO change_tasks (id, request_id, repo_id, seq, title, kind, in_scope, "
            "out_scope, acceptance, depends_on) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                str(uuid.uuid4()), change_id, str(change["repo_id"]), seq,
                task["title"], task["kind"],
                json.dumps(task["in_scope"], ensure_ascii=False),
                json.dumps(task["out_scope"], ensure_ascii=False),
                task["acceptance"],
                json.dumps(task["depends_on"], ensure_ascii=False),
            ),
        )
    await execute(
        "UPDATE change_requests SET status = 'plan_ready', plan_notes = %s, error = NULL, "
        "updated_at = now() WHERE id = %s",
        (str(data.get("summary") or "")[:4000], change_id),
    )
    return await get_change(change_id, user_id)


def _rules_text(repo: dict) -> str:
    from app.core.agent.rules import load_repo_rules
    rules = load_repo_rules([repo])
    return "\n\n".join(r["content"] for r in rules)[:4000] or "（无）"


def validate_plan(data: dict) -> tuple[list[dict], str | None]:
    raw_tasks = data.get("tasks") if isinstance(data, dict) else None
    if not isinstance(raw_tasks, list) or not raw_tasks:
        return [], "计划缺少任务"
    if len(raw_tasks) > MAX_TASKS:
        return [], f"任务过多（最多 {MAX_TASKS} 个）"
    tasks: list[dict] = []
    for seq, raw in enumerate(raw_tasks, 1):
        if not isinstance(raw, dict):
            return [], f"第 {seq} 个任务格式非法"
        kind = str(raw.get("kind") or "feature").strip()
        if kind not in TEMPLATES:
            return [], f"第 {seq} 个任务类型不支持：{kind}"
        acceptance = str(raw.get("acceptance") or "").strip()
        if len(acceptance) < 8:
            return [], f"第 {seq} 个任务缺少可判定验收"
        title = str(raw.get("title") or f"任务 {seq}").strip()[:200]
        in_scope = _scope_list(raw.get("in_scope"))
        out_scope = _scope_list(raw.get("out_scope"))
        depends = raw.get("depends_on") or []
        if not isinstance(depends, list):
            return [], f"第 {seq} 个任务的 depends_on 必须是数组"
        deps: list[int] = []
        for dep in depends:
            try:
                value = int(dep)
            except (TypeError, ValueError):
                return [], f"第 {seq} 个任务依赖非法：{dep}"
            if value < 1 or value >= seq:
                return [], f"第 {seq} 个任务只能依赖前面的任务（收到 {value}）"
            deps.append(value)
        tasks.append({
            "title": title, "kind": kind,
            "in_scope": in_scope, "out_scope": out_scope,
            "acceptance": acceptance[:1000],
            "depends_on": sorted(set(deps)),
        })
    return tasks, None


def _scope_list(value) -> list[str]:
    out = []
    for item in value if isinstance(value, list) else []:
        path = try_normalize_relpath(str(item or ""))
        if path:
            out.append(path[:200])
        if len(out) >= MAX_LIST_ITEMS:
            break
    return out


async def approve_plan(change_id: str, user_id: int) -> dict:
    change = await get_change(change_id, user_id)
    if not change:
        raise ValueError("变更不存在")
    if change["status"] != "plan_ready":
        raise ValueError("当前没有待确认的计划")
    await execute(
        "UPDATE change_requests SET status = 'plan_approved', updated_at = now() WHERE id = %s",
        (change_id,),
    )
    return await get_change(change_id, user_id)


async def get_change(change_id: str, user_id: int) -> dict | None:
    rows = await query(
        """
        SELECT c.id, c.user_id, c.repo_id, r.name, c.title, c.requirements, c.goal,
               c.in_scope, c.out_scope, c.interfaces, c.acceptance_cases, c.nfr,
               c.open_questions, c.status, c.version, c.plan_notes, c.proposal,
               c.evidence, c.error, c.job_id, c.approved_at, c.created_at, c.updated_at
        FROM change_requests c JOIN repos r ON r.id = c.repo_id
        WHERE c.id = %s AND c.user_id = %s
        """,
        (change_id, user_id),
    )
    if not rows:
        return None
    r = rows[0]
    task_rows = await query(
        "SELECT id, seq, title, kind, in_scope, out_scope, acceptance, depends_on, "
        "status, attempts, result FROM change_tasks WHERE request_id = %s ORDER BY seq",
        (change_id,),
    )
    tasks = [
        {
            "id": str(t[0]), "seq": t[1], "title": t[2], "kind": t[3],
            "in_scope": t[4] or [], "out_scope": t[5] or [],
            "acceptance": t[6], "depends_on": t[7] or [],
            "status": t[8], "attempts": t[9], "result": t[10] or {},
        }
        for t in task_rows
    ]
    return {
        "id": str(r[0]), "user_id": r[1], "repo_id": str(r[2]), "repo_name": r[3],
        "title": r[4], "requirements": r[5], "goal": r[6],
        "in_scope": r[7] or [], "out_scope": r[8] or [],
        "interfaces": r[9] or [], "acceptance_cases": r[10] or [],
        "nfr": r[11] or [], "open_questions": r[12] or [],
        "status": r[13], "version": r[14], "plan_notes": r[15] or "",
        "proposal": r[16] or {}, "evidence": r[17] or {}, "error": r[18],
        "job_id": str(r[19]) if r[19] else None,
        "approved_at": r[20], "created_at": r[21], "updated_at": r[22],
        "tasks": tasks,
    }


async def list_changes(user_id: int, limit: int = 50) -> list[dict]:
    rows = await query(
        """
        SELECT c.id, c.title, c.status, c.version, c.repo_id, r.name, c.error,
               c.created_at, c.updated_at,
               (SELECT COUNT(*) FROM change_tasks t WHERE t.request_id = c.id)
        FROM change_requests c JOIN repos r ON r.id = c.repo_id
        WHERE c.user_id = %s ORDER BY c.created_at DESC LIMIT %s
        """,
        (user_id, max(1, min(limit, 100))),
    )
    return [
        {
            "id": str(r[0]), "title": r[1], "status": r[2], "version": r[3],
            "repo_id": str(r[4]), "repo_name": r[5], "error": r[6],
            "created_at": r[7], "updated_at": r[8], "task_count": int(r[9] or 0),
        }
        for r in rows
    ]


async def _load_raw(change_id: str) -> dict | None:
    rows = await query(
        "SELECT id, user_id, repo_id, title, requirements, status FROM change_requests "
        "WHERE id = %s",
        (change_id,),
    )
    if not rows:
        return None
    return {
        "id": str(rows[0][0]), "user_id": rows[0][1], "repo_id": str(rows[0][2]),
        "title": rows[0][3], "requirements": rows[0][4], "status": rows[0][5],
    }


async def _set_status(change_id: str, status: str, error: str | None = None) -> None:
    await execute(
        "UPDATE change_requests SET status = %s, error = %s, updated_at = now() WHERE id = %s",
        (status, error[:2000] if error else None, change_id),
    )


async def set_change_job(change_id: str, job_id: str | None) -> None:
    await execute(
        "UPDATE change_requests SET job_id = %s, updated_at = now() WHERE id = %s",
        (job_id, change_id),
    )


async def set_change_status(change_id: str, status: str, error: str | None = None) -> None:
    await _set_status(change_id, status, error)


async def set_proposal(change_id: str, proposal: dict) -> None:
    await execute(
        "UPDATE change_requests SET proposal = %s, updated_at = now() WHERE id = %s",
        (json.dumps(proposal, ensure_ascii=False), change_id),
    )


async def set_evidence(change_id: str, evidence: dict) -> None:
    await execute(
        "UPDATE change_requests SET evidence = %s, updated_at = now() WHERE id = %s",
        (json.dumps(evidence, ensure_ascii=False), change_id),
    )

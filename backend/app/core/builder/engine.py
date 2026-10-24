"""Builder: greenfield project plan → file proposal → human-approved write.

Python mode generates a FastAPI backend.  Fullstack mode first generates an
OpenAPI contract and backend, then deterministically scaffolds a typed
TypeScript frontend and runs both stacks through the verification gate.
"""
import json
from pathlib import Path

import structlog

from app.config import settings
from app.core.conflicts import ConflictError
from app.core.llm.json_call import llm_json
from app.core.sandbox.runtime import execute as sandbox_execute, sandbox_status
from app.core.security.limits import ensure_token_budget
from app.core.security.paths import (
    UnsafePathError, is_secret_path, resolve_repo_path, try_normalize_relpath,
)
from app.core.security.test_guard import assert_changes_preserve_tests
from app.core.verify.service import run_verification
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

FULLSTACK_PLAN_PROMPT = """你是资深全栈架构师。请为下面的需求设计一个契约优先的全栈项目方案。

需求：
{requirements}

项目约定（AGENTS.md）：
{rules}

约束：
- 单一契约源：contracts/openapi.json（OpenAPI 3.1），后端路由与前端类型都必须由它派生
- 后端：Python 3.12 + FastAPI + SQLite（sqlite3）+ pytest，requirements 只放 fastapi / uvicorn / pytest / httpx
- 前端：TypeScript API Explorer，由 OpenAPI 生成类型；系统会自动生成前端，不需要你规划具体前端文件
- 后端 API 路径/方法/响应字段必须与契约一致
- 结构清晰、有基础错误处理与测试

只输出 JSON（不要 markdown 代码块）：
{{
 "summary": "一句话概述",
 "stack": ["OpenAPI 3.1", "Python 3.12", "FastAPI", "SQLite", "TypeScript"],
 "structure": [{{"path": "contracts/openapi.json", "purpose": "单一契约源"}}, {{"path": "app/main.py", "purpose": "FastAPI 入口"}}],
 "data_model": [{{"table": "items", "fields": ["id INTEGER PRIMARY KEY", "title TEXT NOT NULL"]}}],
 "api": [{{"method": "GET", "path": "/items", "description": "列出全部"}}],
 "milestones": [{{"name": "契约与后端", "tasks": ["定义 OpenAPI", "实现路由", "补测试"], "verification": "pytest tests/ -q"}}, {{"name": "前端与双栈 Gate", "tasks": ["生成 TS 类型", "构建前端"], "verification": "npm run build"}}],
 "risks": ["..."]
}}"""

FULLSTACK_FILES_PROMPT = """根据已确认的方案，生成 OpenAPI 契约与 FastAPI 后端文件。

方案：
{plan}

项目约定：
{rules}

{feedback}

要求：
- 必须先生成 contracts/openapi.json：合法 OpenAPI 3.1 JSON，包含项目所有 paths 与 components.schemas
- 后端 FastAPI 路由、请求/响应字段必须与契约一致；SQLite 持久化
- 必须包含 README.md、requirements.txt、.gitignore、AGENTS.md、app/ 实现、tests/ pytest 用例
- tests 中至少覆盖契约中的主要接口；不要删除/跳过测试
- 不要生成 frontend/、根 package.json、nova.yaml；系统会自动生成 TypeScript 前端与契约配置
- 每个文件完整内容，不要省略；文件总数 ≤ {max_files}；相对路径
- 后端必须能 uvicorn app.main:app 启动

只输出 JSON：
{{"files": [{{"path": "contracts/openapi.json", "content": "..."}}], "notes": "实现要点"}}"""

FULLSTACK_REPAIR_PROMPT = """上一轮全栈生成没有通过 Gate。请根据真实失败输出修正契约与后端实现。

方案：
{plan}

失败摘要：
{failure}

当前契约：
{contract}

当前后端 / 测试文件（节选）：
{backend}

要求：
- 保持 OpenAPI 契约与 FastAPI 后端、pytest 用例三者一致
- 只输出需要修改的文件（可包含 contract / app / tests），完整内容，不要省略
- 不要生成 frontend/、根 package.json、nova.yaml
- 文件总数 ≤ {max_files}

只输出 JSON：
{{"files": [{{"path": "app/main.py", "content": "..."}}], "notes": "修复说明"}}"""


async def _set(repo_id: str, **fields) -> None:
    sets, params = [], []
    for key, value in fields.items():
        sets.append(f"{key} = %s")
        params.append(json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value)
    sets.append("updated_at = now()")
    await execute(f"UPDATE repos SET {', '.join(sets)} WHERE id = %s", (*params, repo_id))


async def load_builder(repo_id: str) -> dict | None:
    rows = await query(
        "SELECT id, user_id, name, root_path, status, kind, brief, rules, plan, proposal, error, stack_mode "
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
        "stack_mode": r[11] or "python",
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


CONTRACT_TEST = """import json
from pathlib import Path

from app.main import app


def test_contract_paths_are_implemented():
    contract = json.loads(Path("contracts/openapi.json").read_text(encoding="utf-8"))
    implemented = app.openapi().get("paths", {})
    for path, methods in (contract.get("paths") or {}).items():
        assert path in implemented, f"missing path: {path}"
        for method in methods:
            if method.lower() in {"get", "post", "put", "patch", "delete"}:
                assert method.lower() in implemented[path], f"missing {method} {path}"
"""

FRONTEND_PACKAGE = """{
  "name": "nova-fullstack-frontend",
  "private": true,
  "scripts": {
    "lint": "node frontend/scripts/lint.js",
    "test": "node --test frontend/test",
    "build": "tsc -p tsconfig.json"
  }
}
"""

FRONTEND_TSCONFIG = """{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "strict": true,
    "noEmit": false,
    "outDir": "frontend/dist",
    "lib": ["ES2022", "DOM"],
    "skipLibCheck": true
  },
  "include": ["frontend/src"]
}
"""

FRONTEND_INDEX = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>__TITLE__ · API Explorer</title>
  <style>
    body { font-family: system-ui, sans-serif; margin: 2rem; background: #0b0e14; color: #e7eaf3; }
    .grid { display: flex; flex-wrap: wrap; gap: 8px; margin: 1rem 0; }
    button { padding: 8px 12px; border-radius: 6px; border: 1px solid #334; background: #161d29; color: #cfe; cursor: pointer; }
    button:hover { border-color: #6c8cff; }
    pre { background: #11161f; padding: 12px; border-radius: 8px; min-height: 120px; white-space: pre-wrap; }
  </style>
</head>
<body>
  <div id="app"></div>
  <script type="module" src="./dist/app.js"></script>
</body>
</html>
"""

FRONTEND_APP = """import { endpoints } from './endpoints';

const root = document.querySelector<HTMLDivElement>('#app');
if (root) {
  const title = document.createElement('h1');
  title.textContent = '__TITLE__ API Explorer';
  const hint = document.createElement('p');
  hint.textContent = '接口来自 contracts/openapi.json，类型由 openapi-typescript 生成。';
  const grid = document.createElement('div');
  grid.className = 'grid';
  const output = document.createElement('pre');
  output.textContent = '点击接口发起请求';

  for (const endpoint of endpoints) {
    const button = document.createElement('button');
    button.textContent = endpoint;
    button.addEventListener('click', async () => {
      output.textContent = '请求中…';
      try {
        const response = await fetch(endpoint);
        output.textContent = `${response.status}\\n${await response.text()}`;
      } catch (error) {
        output.textContent = String(error);
      }
    });
    grid.appendChild(button);
  }
  root.append(title, hint, grid, output);
}
"""

FRONTEND_TEST = """const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');

test('frontend endpoints match the committed contract', () => {
  const contract = JSON.parse(fs.readFileSync('contracts/openapi.json', 'utf8'));
  const endpoints = JSON.parse(fs.readFileSync('frontend/src/endpoints.json', 'utf8'));
  assert.deepStrictEqual(
    [...endpoints].sort(),
    Object.keys(contract.paths || {}).sort(),
  );
});
"""

FRONTEND_LINT = """const fs = require('node:fs');

const required = [
  'contracts/openapi.json',
  'frontend/src/app.ts',
  'frontend/src/endpoints.ts',
  'frontend/src/endpoints.json',
  'frontend/src/lib/api-schema.d.ts',
  'frontend/index.html',
  'tsconfig.json',
];
for (const file of required) {
  if (!fs.readFileSync(file, 'utf8').trim()) {
    console.error(`empty file: ${file}`);
    process.exit(1);
  }
}
const contract = JSON.parse(fs.readFileSync('contracts/openapi.json', 'utf8'));
const endpoints = JSON.parse(fs.readFileSync('frontend/src/endpoints.json', 'utf8'));
const expected = Object.keys(contract.paths || {}).sort();
if (JSON.stringify([...endpoints].sort()) !== JSON.stringify(expected)) {
  console.error('frontend endpoints drift from contract');
  process.exit(1);
}
console.log('lint ok');
"""

FRONTEND_README = """# Frontend

Contract-driven TypeScript API Explorer.

- `contracts/openapi.json` is the single source of truth.
- `src/lib/api-schema.d.ts` is generated by `openapi-typescript`.
- `npm run build` compiles with the global TypeScript compiler.
- `npm test` checks that the explorer endpoint list matches the contract.
"""


def _parse_contract(text: str) -> dict:
    try:
        data = json.loads(text)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"contracts/openapi.json 不是合法 JSON：{exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("OpenAPI 契约必须是对象")
    if not str(data.get("openapi") or "").startswith("3."):
        raise ValueError("OpenAPI 契约缺少 3.x 的 openapi 版本")
    paths = data.get("paths")
    if not isinstance(paths, dict) or not paths:
        raise ValueError("OpenAPI 契约缺少 paths")
    return data


def _frontend_files(name: str, paths: list[str]) -> dict[str, str]:
    title = name.replace("<", "").replace(">", "").strip()[:60] or "Project"
    endpoints_ts = json.dumps(paths, ensure_ascii=False)
    endpoints_json = json.dumps(paths, ensure_ascii=False, indent=2)
    return {
        "package.json": FRONTEND_PACKAGE,
        "tsconfig.json": FRONTEND_TSCONFIG,
        "frontend/index.html": FRONTEND_INDEX.replace("__TITLE__", title),
        "frontend/src/app.ts": FRONTEND_APP.replace("__TITLE__", title),
        "frontend/src/endpoints.ts": (
            "import type { paths } from './lib/api-schema';\n\n"
            f"export const endpoints = {endpoints_ts} as const "
            "satisfies readonly (keyof paths)[];\n"
        ),
        "frontend/src/endpoints.json": endpoints_json + "\n",
        "frontend/test/contract.test.js": FRONTEND_TEST,
        "frontend/scripts/lint.js": FRONTEND_LINT,
        "frontend/README.md": FRONTEND_README,
    }


async def _generate_contract_types(contract_text: str) -> str:
    status = await sandbox_status()
    if not status.get("node_available"):
        raise ValueError("nova-node 镜像未就绪，无法生成前端契约类型")
    command = (
        "openapi-typescript contracts/openapi.json "
        "-o frontend/src/lib/api-schema.d.ts >/dev/null 2>&1 "
        "&& cat frontend/src/lib/api-schema.d.ts"
    )
    result = await sandbox_execute(
        files={"contracts/openapi.json": contract_text},
        command=command,
        timeout=90,
        image=settings.sandbox_node_image,
    )
    if result.get("exit_code") != 0:
        raise ValueError(
            "openapi-typescript 生成失败："
            + (result.get("stderr") or result.get("stdout") or "")[-1200:]
        )
    types = (result.get("stdout") or "").strip()
    if not types:
        raise ValueError("openapi-typescript 没有产出类型文件")
    return types + "\n"


async def _finalize_fullstack(files: dict[str, str], name: str) -> dict[str, str]:
    contract_text = files.get("contracts/openapi.json")
    if not contract_text:
        raise ValueError("全栈生成缺少 contracts/openapi.json")
    contract = _parse_contract(contract_text)
    files = {
        path: content for path, content in files.items()
        if not path.startswith("frontend/")
        and path not in ("package.json", "nova.yaml")
    }
    contract_text = json.dumps(contract, ensure_ascii=False, indent=2) + "\n"
    files["contracts/openapi.json"] = contract_text
    files["frontend/src/lib/api-schema.d.ts"] = await _generate_contract_types(contract_text)
    files.update(_frontend_files(name, sorted(contract["paths"].keys())))
    files["tests/test_contract.py"] = CONTRACT_TEST
    files["nova.yaml"] = (
        "contract:\n"
        "  source: contracts/openapi.json\n"
        "  target: frontend/src/lib/api-schema.d.ts\n"
    )
    if len(files) > MAX_FILES:
        raise ValueError(f"全栈文件过多（{len(files)} > {MAX_FILES}）")
    if sum(len(content) for content in files.values()) > MAX_TOTAL_CHARS:
        raise ValueError("全栈生成内容超过体积上限")
    return files


def _compact_gate(gate: dict) -> dict:
    return {
        "status": gate.get("status"),
        "stack": gate.get("stack"),
        "notes": (gate.get("notes") or [])[:8],
        "exit_code": gate.get("exit_code"),
        "elapsed_ms": gate.get("elapsed_ms"),
        "steps": [
            {
                "name": step.get("name"), "status": step.get("status"),
                "exit_code": step.get("exit_code"),
                "stdout": (step.get("stdout") or "")[-1500:],
                "stderr": (step.get("stderr") or "")[-800:],
            }
            for step in gate.get("steps", [])
        ],
    }


def _gate_failure_text(gate: dict) -> str:
    failed = [step for step in gate.get("steps", []) if step.get("status") == "failed"]
    if not failed:
        return "\n".join(gate.get("notes") or [])[:4000] or "Gate failed"
    parts = []
    for step in failed:
        parts.append(
            f"$ {step.get('name')} (exit {step.get('exit_code')})\n"
            f"{(step.get('stdout') or '')[-2500:]}\n{(step.get('stderr') or '')[-1200:]}"
        )
    return "\n\n".join(parts)[:6000]


def _repair_context(files: dict[str, str]) -> str:
    selected = []
    for path in sorted(files):
        if path == "contracts/openapi.json" or path.startswith(("app/", "tests/")):
            selected.append(f"--- {path} ---\n{files[path][:4000]}")
        if len(selected) >= 10:
            break
    return "\n\n".join(selected) or "（无）"


async def _builder_gate(repo: dict, files: dict[str, str]) -> dict:
    try:
        user_rows = await query(
            "SELECT id, username, role FROM users WHERE id = %s",
            (repo["user_id"],),
        )
        if not user_rows:
            raise RuntimeError("项目归属账号不存在")
        user = {
            "id": user_rows[0][0], "username": user_rows[0][1],
            "role": user_rows[0][2],
        }
        return await run_verification(repo, user, overrides=files)
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "failed", "stack": "fullstack",
            "notes": [f"Gate 执行失败：{exc}"], "steps": [], "exit_code": -1,
        }


async def generate_plan(repo_id: str, ctx=None) -> None:
    repo = await load_builder(repo_id)
    if not repo:
        return
    try:
        if ctx:
            await ctx.check_cancel()
        await _set(repo_id, status="planning", error=None)
        await ensure_token_budget(user_id=repo["user_id"])
        prompt = (
            FULLSTACK_PLAN_PROMPT if repo.get("stack_mode") == "fullstack" else PLAN_PROMPT
        )
        data = await llm_json(
            prompt.format(
                requirements=repo["brief"][:6000],
                rules=repo["rules"][:3000] or "（无）",
            ),
            user_id=repo["user_id"], source="builder", purpose="plan",
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
        prompt = (
            FULLSTACK_FILES_PROMPT
            if repo.get("stack_mode") == "fullstack"
            else FILES_PROMPT
        )
        data = await llm_json(
            prompt.format(
                plan=json.dumps(repo["plan"], ensure_ascii=False)[:20000],
                rules=repo["rules"][:3000] or "（无）",
                feedback=f"上一轮审阅反馈（请针对性修改）：{feedback[:2000]}" if feedback else "",
                max_files=MAX_FILES,
            ),
            user_id=repo["user_id"], source="builder", purpose="plan",
        )
        if ctx:
            await ctx.check_cancel()
        files = validate_files(data.get("files"))
        if not files:
            raise ValueError("模型没有产出有效文件")
        notes = str(data.get("notes", ""))[:3000]
        gate = None
        repair_attempts = 0
        if repo.get("stack_mode") == "fullstack":
            files = await _finalize_fullstack(files, repo["name"])
            if ctx:
                await ctx.update(progress=0.85, step="双栈 Gate")
            gate = await _builder_gate(repo, files)
            while gate.get("status") == "failed" and repair_attempts < 1:
                repair_attempts += 1
                if ctx:
                    await ctx.update(progress=0.92, step=f"按 Gate 失败修复（{repair_attempts}/1）")
                try:
                    repair_data = await llm_json(
                        FULLSTACK_REPAIR_PROMPT.format(
                            plan=json.dumps(repo["plan"], ensure_ascii=False)[:12000],
                            failure=_gate_failure_text(gate),
                            contract=(files.get("contracts/openapi.json") or "")[:12000],
                            backend=_repair_context(files),
                            max_files=MAX_FILES,
                        ),
                        user_id=repo["user_id"], source="builder", purpose="plan",
                    )
                    repaired = validate_files(repair_data.get("files"))
                    if not repaired:
                        break
                    files.update(repaired)
                    files = await _finalize_fullstack(files, repo["name"])
                    notes = str(repair_data.get("notes") or notes)[:3000]
                    gate = await _builder_gate(repo, files)
                except Exception as exc:  # noqa: BLE001
                    gate = {
                        "status": "failed", "stack": "fullstack",
                        "notes": [f"修复阶段失败：{exc}"], "steps": [], "exit_code": -1,
                    }
                    break
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
            "notes": notes,
            "feedback": feedback[:2000],
            "gate": _compact_gate(gate) if gate else None,
            "repair_attempts": repair_attempts,
        }
        gate_error = None
        if gate and gate.get("status") != "passed":
            gate_error = "双栈 Gate 未通过；请在提案中检查步骤输出，退回重做后再批准"
        await _set(repo_id, proposal=proposal, status="review", error=gate_error)
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
    gate = proposal.get("gate") or {}
    if gate.get("status") == "failed":
        raise RuntimeError("双栈 Gate 未通过，不能写入；请退回重做或重新生成")

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
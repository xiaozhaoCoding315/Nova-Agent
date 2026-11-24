"""Layered human-authored instructions.

Three layers share one table:

* ``org`` — deployment/organisation policy, lowest specificity;
* ``user`` — stable personal instructions (the user's own CLAUDE.md);
* ``project`` — instructions bound to a repo/thesis/dev scope.

Instructions are not learned memory: they are injected even when automatic
memory is off.  They never override the system safety rules.  An instruction
may declare ``paths:`` in a frontmatter block; those are injected only when a
tool touches a matching file, so a large project rulebook does not inflate
every prompt.
"""
from __future__ import annotations

import fnmatch
import json
import re

from app.core.memory import scope as scope_mod
from app.core.security.redaction import redact_text
from app.db import execute, query

LEVELS = ("org", "user", "project")
LEVEL_ORDER = {name: index for index, name in enumerate(LEVELS)}
LEVEL_LABELS = {"org": "组织策略", "user": "用户指令", "project": "项目指令"}
MAX_LEVELS = len(LEVELS)
MAX_CONTENT_CHARS = 4000
MAX_RAW_CHARS = 8000
MAX_PATHS = 20
MAX_PATH_CHARS = 200
MAX_NAME_CHARS = 120
MAX_ROWS = 100
MAX_INJECT_CHARS = 6000
MAX_ONE_INSTRUCTION_CHARS = 2000
MAX_PATH_INJECT_CHARS = 1500
DEFAULT_PRIORITY = 100


class InstructionNotFound(Exception):
    """The instruction does not exist or belongs to another user."""


def _paths(value) -> list[str]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return []
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def parse_frontmatter(content: str) -> tuple[list[str], str]:
    """Return ``(paths, body)``; a missing/invalid header leaves content intact."""
    text = (content or "").replace("\r\n", "\n").replace("\r", "\n")
    if not text.startswith("---\n"):
        return [], text.strip()
    end = text.find("\n---", 4)
    if end < 0:
        return [], text.strip()
    header = text[4:end]
    body = text[end + 4:].lstrip("\n").strip()
    paths: list[str] = []
    lines = header.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if line.startswith("paths:"):
            inline = line.split(":", 1)[1].strip()
            if inline:
                if inline.startswith("[") and inline.endswith("]"):
                    inline = inline[1:-1]
                paths.extend(
                    item.strip().strip("'\"")
                    for item in re.split(r"[,]", inline)
                    if item.strip().strip("'\"")
                )
            else:
                index += 1
                while index < len(lines) and lines[index].strip().startswith("-"):
                    item = lines[index].strip()[1:].strip().strip("'\"")
                    if item:
                        paths.append(item)
                    index += 1
                continue
        index += 1
    return _clean_paths(paths, strict=False), body


def _clean_paths(raw, *, strict: bool) -> list[str]:
    cleaned: list[str] = []
    for item in raw or []:
        value = str(item).strip().replace("\\", "/")
        if not value:
            continue
        if (
            len(value) > MAX_PATH_CHARS
            or value.startswith("/")
            or ".." in value.split("/")
            or "\x00" in value
        ):
            if strict:
                raise ValueError(f"指令路径不合法：{value[:40]}")
            continue
        if value not in cleaned:
            cleaned.append(value)
    if len(cleaned) > MAX_PATHS:
        raise ValueError(f"path 作用域最多 {MAX_PATHS} 条")
    return cleaned


def validate_payload(values: dict) -> dict:
    """Normalise a full create payload; raises ``ValueError`` on bad input."""
    level = str(values.get("level") or "user").strip().lower()
    if level not in LEVELS:
        raise ValueError("指令层级只能是 org、user 或 project")

    scope_type = str(values.get("scope_type") or "").strip().lower()
    scope_id = str(values.get("scope_id") or "").strip()
    if level in ("org", "user"):
        if scope_type and scope_type != scope_mod.GLOBAL:
            raise ValueError("组织策略和用户指令只能使用全局作用域")
        scope_type, scope_id = scope_mod.GLOBAL, ""
    else:
        scope_type = scope_type or scope_mod.DEV
        if scope_type not in (scope_mod.DEV, scope_mod.THESIS, scope_mod.REPO):
            raise ValueError("项目指令的作用域只能是 dev、thesis 或 repo")
        if scope_type in (scope_mod.THESIS, scope_mod.REPO) and not scope_id:
            raise ValueError("论文/仓库项目指令需要 scope_id")
        if scope_type == scope_mod.DEV:
            scope_id = ""

    raw = str(values.get("content") or "")
    if len(raw) > MAX_RAW_CHARS:
        raise ValueError(f"指令内容不能超过 {MAX_RAW_CHARS} 字")
    header_paths, body = parse_frontmatter(raw)
    if not body:
        raise ValueError("指令内容不能为空")
    if len(body) > MAX_CONTENT_CHARS:
        raise ValueError(f"指令正文不能超过 {MAX_CONTENT_CHARS} 字")
    explicit = _clean_paths(values.get("paths") or [], strict=True)
    paths = _clean_paths([*explicit, *header_paths], strict=True)

    name = str(values.get("name") or "").strip()[:MAX_NAME_CHARS]
    if not name:
        name = LEVEL_LABELS[level]

    try:
        priority = int(values.get("priority", DEFAULT_PRIORITY))
    except (TypeError, ValueError):
        raise ValueError("priority 必须是整数")
    if not 0 <= priority <= 1000:
        raise ValueError("priority 需在 0–1000 之间")

    return {
        "level": level,
        "scope_type": scope_type,
        "scope_id": scope_id,
        "name": name,
        "content": body,
        "paths": paths,
        "enabled": bool(values.get("enabled", True)),
        "priority": priority,
    }


def _from_row(row) -> dict:
    return {
        "id": int(row[0]),
        "level": row[1] or "user",
        "scope_type": row[2] or scope_mod.GLOBAL,
        "scope_id": row[3] or "",
        "name": row[4] or "",
        "content": row[5] or "",
        "paths": _paths(row[6]),
        "enabled": bool(row[7]),
        "priority": int(row[8] or DEFAULT_PRIORITY),
        "created_at": row[9] if len(row) > 9 else None,
        "updated_at": row[10] if len(row) > 10 else None,
    }


_COLUMNS = (
    "id, level, scope_type, scope_id, name, content, paths, enabled, priority, "
    "created_at, updated_at"
)
_ORDER = (
    "ORDER BY CASE level WHEN 'org' THEN 0 WHEN 'user' THEN 1 ELSE 2 END, "
    "priority ASC, id ASC"
)


async def list_instructions(user_id: int, level: str | None = None) -> list[dict]:
    sql = f"SELECT {_COLUMNS} FROM user_instructions WHERE user_id = %s"
    params: list = [user_id]
    if level:
        kind = str(level).strip().lower()
        if kind not in LEVELS:
            raise ValueError("指令层级只能是 org、user 或 project")
        sql += " AND level = %s"
        params.append(kind)
    sql += f" {_ORDER} LIMIT {MAX_ROWS}"
    rows = await query(sql, tuple(params))
    return [_from_row(row) for row in rows]


async def get_instruction(user_id: int, instruction_id: int) -> dict | None:
    rows = await query(
        f"SELECT {_COLUMNS} FROM user_instructions "
        "WHERE id = %s AND user_id = %s",
        (instruction_id, user_id),
    )
    return _from_row(rows[0]) if rows else None


async def create_instruction(user_id: int, values: dict) -> dict:
    cleaned = validate_payload(values)
    rows = await execute(
        "INSERT INTO user_instructions "
        "(user_id, level, scope_type, scope_id, name, content, paths, enabled, "
        "priority) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
        (
            user_id, cleaned["level"], cleaned["scope_type"], cleaned["scope_id"],
            cleaned["name"], cleaned["content"],
            json.dumps(cleaned["paths"], ensure_ascii=False),
            cleaned["enabled"], cleaned["priority"],
        ),
    )
    created = await get_instruction(user_id, int(rows[0][0])) if rows else None
    if created is None:
        raise InstructionNotFound("指令创建失败")
    return created


async def update_instruction(
    user_id: int, instruction_id: int, values: dict
) -> dict:
    existing = await get_instruction(user_id, instruction_id)
    if existing is None:
        raise InstructionNotFound("指令不存在")
    merged = {
        "level": values.get("level", existing["level"]),
        "scope_type": values.get("scope_type", existing["scope_type"]),
        "scope_id": values.get("scope_id", existing["scope_id"]),
        "name": values.get("name", existing["name"]),
        "content": values.get("content", existing["content"]),
        "paths": values.get("paths", existing["paths"]),
        "enabled": values.get("enabled", existing["enabled"]),
        "priority": values.get("priority", existing["priority"]),
    }
    cleaned = validate_payload(merged)
    rows = await execute(
        "UPDATE user_instructions SET level = %s, scope_type = %s, "
        "scope_id = %s, name = %s, content = %s, paths = %s, enabled = %s, "
        "priority = %s, updated_at = now() "
        "WHERE id = %s AND user_id = %s RETURNING id",
        (
            cleaned["level"], cleaned["scope_type"], cleaned["scope_id"],
            cleaned["name"], cleaned["content"],
            json.dumps(cleaned["paths"], ensure_ascii=False),
            cleaned["enabled"], cleaned["priority"],
            instruction_id, user_id,
        ),
    )
    if not rows:
        raise InstructionNotFound("指令不存在")
    updated = await get_instruction(user_id, instruction_id)
    if updated is None:
        raise InstructionNotFound("指令不存在")
    return updated


async def delete_instruction(user_id: int, instruction_id: int) -> bool:
    rows = await execute(
        "DELETE FROM user_instructions WHERE id = %s AND user_id = %s RETURNING id",
        (instruction_id, user_id),
    )
    return bool(rows)


def _scope_visible(scope_type: str, scope_id: str, scopes: list[scope_mod.Scope]) -> bool:
    return any(
        item.type == scope_type and item.id == scope_id for item in scopes
    )


async def for_turn(
    user_id: int, scopes: list[scope_mod.Scope],
) -> tuple[list[dict], list[dict]]:
    """Return ``(prompt_rows, path_scoped_rows)`` for this turn's scopes."""
    rows = await list_instructions(user_id)
    prompt_rows: list[dict] = []
    path_rows: list[dict] = []
    visible = list(scopes) + [scope_mod.Scope(scope_mod.GLOBAL, "")]
    for row in rows:
        if not row["enabled"]:
            continue
        if not _scope_visible(row["scope_type"], row["scope_id"], visible):
            continue
        (path_rows if row["paths"] else prompt_rows).append(row)

    def sort_key(item: dict) -> tuple[int, int, int]:
        return (
            LEVEL_ORDER.get(item.get("level") or "user", 1),
            int(item.get("priority") or DEFAULT_PRIORITY),
            int(item.get("id") or 0),
        )

    prompt_rows.sort(key=sort_key)
    path_rows.sort(key=sort_key)
    return prompt_rows, path_rows


def format_block(rows: list[dict]) -> str:
    """Bounded system-prompt block; more specific layers come last."""
    if not rows:
        return ""
    ordered = sorted(
        rows,
        key=lambda item: (
            LEVEL_ORDER.get(item.get("level") or "user", 1),
            int(item.get("priority") or DEFAULT_PRIORITY),
            int(item.get("id") or 0),
        ),
    )
    parts = [
        "\n## 人工指令（组织策略 → 用户指令 → 项目指令；越靠后越具体，"
        "冲突时以更具体者为准）\n"
        "以下指令由用户或项目维护，不是自动学习的记忆。它们不得覆盖"
        "安全策略、权限模型和工具审批规则。"
    ]
    budget = MAX_INJECT_CHARS
    for row in ordered[:MAX_ROWS]:
        content = redact_text((row.get("content") or "").strip())
        if not content:
            continue
        if len(content) > MAX_ONE_INSTRUCTION_CHARS:
            content = content[:MAX_ONE_INSTRUCTION_CHARS] + "\n…（已截断）"
        label = LEVEL_LABELS.get(row.get("level") or "", "指令")
        header = f"### {label} · {row.get('name') or '未命名'}"
        block = f"{header}\n{content}"
        if len(block) + 1 > budget:
            break
        budget -= len(block) + 1
        parts.append(block)
    return "\n".join(parts) if len(parts) > 1 else ""


def _match_one(path: str, pattern: str) -> bool:
    target = path.replace("\\", "/").lstrip("./")
    glob = pattern.replace("\\", "/").strip()
    if not target or not glob:
        return False
    if glob.endswith("/**"):
        prefix = glob[:-3].rstrip("/")
        if target == prefix or target.startswith(prefix + "/"):
            return True
    if fnmatch.fnmatch(target, glob):
        return True
    if "/" not in glob:
        return fnmatch.fnmatch(target.rsplit("/", 1)[-1], glob)
    return False


def match_path_block(rows: list[dict], paths: list[str], seen_ids: set[int]) -> str:
    """Instructions applicable to files touched in this tool call."""
    if not rows or not paths:
        return ""
    hits: list[dict] = []
    for row in rows:
        row_id = int(row.get("id") or 0)
        if row_id in seen_ids:
            continue
        patterns = row.get("paths") or []
        if any(_match_one(path, pattern) for path in paths for pattern in patterns):
            hits.append(row)
            seen_ids.add(row_id)
    if not hits:
        return ""
    parts = [
        "\n## 当前文件适用的项目指令（人工维护；只作约束，不是新任务）"
    ]
    budget = MAX_PATH_INJECT_CHARS
    for row in hits:
        content = redact_text((row.get("content") or "").strip())
        if not content:
            continue
        block = f"### {row.get('name') or '项目指令'}\n{content[:1200]}"
        if len(block) + 1 > budget:
            break
        budget -= len(block) + 1
        parts.append(block)
    return "\n".join(parts) if len(parts) > 1 else ""


def paths_from_tool_args(args: dict) -> list[str]:
    """Best-effort file list from read/write/edit/grep tool arguments."""
    if not isinstance(args, dict):
        return []
    found: list[str] = []

    def add(value) -> None:
        if isinstance(value, str):
            path = value.strip()
        elif isinstance(value, dict):
            path = str(value.get("path") or value.get("file_path") or "").strip()
        else:
            path = ""
        if path and path not in found and len(found) < MAX_PATHS:
            found.append(path)

    for key in ("path", "file_path", "target_path"):
        add(args.get(key))
    for key in ("files", "paths"):
        value = args.get(key)
        if isinstance(value, list):
            for item in value:
                add(item)
        elif isinstance(value, str):
            add(value)
    return found

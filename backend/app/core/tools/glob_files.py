"""glob tool: find repository files by pattern, newest first."""
import asyncio
from pathlib import Path

from app.core.security.paths import is_secret_path
from app.core.tools._search import (
    glob_to_regex, is_inside, iter_files, resolve_scope,
)
from app.core.tools.base import ToolBusinessError, ToolContext, ToolDefinition

MAX_LIMIT = 500
DEFAULT_LIMIT = 200


def _collect(
    root: Path, start: Path, regex, limit: int
) -> tuple[list[dict], bool]:
    entries: list[dict] = []
    for path in iter_files(root, start):
        if not is_inside(root, path):
            continue
        try:
            rel = path.relative_to(root).as_posix()
        except ValueError:
            continue
        if is_secret_path(rel):
            continue
        name = path.name
        if not (regex.match(rel) or regex.match(name)):
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        entries.append({
            "path": rel,
            "size": stat.st_size,
            "mtime": int(stat.st_mtime),
        })
    entries.sort(key=lambda item: item["mtime"], reverse=True)
    return entries[:limit], len(entries) > limit


async def glob_files(args: dict, ctx: ToolContext) -> dict:
    pattern = str(args.get("pattern") or "").strip()
    if not pattern:
        raise ToolBusinessError("pattern 不能为空")
    limit = min(max(int(args.get("limit") or DEFAULT_LIMIT), 1), MAX_LIMIT)
    regex = glob_to_regex(pattern)
    root, start, repo_name = await resolve_scope(args, ctx)
    files, truncated = await asyncio.to_thread(_collect, root, start, regex, limit)
    return {
        "repo": repo_name,
        "files": files,
        "count": len(files),
        "truncated": truncated,
    }


TOOL = ToolDefinition(
    name="glob",
    description=(
        "按文件名/路径模式查找仓库文件（不依赖索引），按修改时间倒序返回。"
        "pattern 支持 *、**、?；不含 / 的模式匹配任意深度的文件名。"
        "用于定位文件；查找文件内容用 grep，语义/符号检索用 search_code。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "glob 模式，如 **/*.tsx 或 *.py"},
            "path": {"type": "string", "description": "限定目录（仓库内相对路径，可选）"},
            "limit": {"type": "integer", "description": "最多返回条数（默认 200，上限 500）"},
            "repo_id": {"type": "string", "description": "仓库 UUID（可选，默认取会话关联仓库）"},
        },
        "required": ["pattern"],
    },
    func=glob_files,
    category="read",
    capabilities=["fs.read"],
    timeout=20,
)

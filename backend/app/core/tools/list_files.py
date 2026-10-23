"""list_files tool: enumerate indexed repo files to locate targets."""
from app.core.indexing.pipeline import get_repo
from app.core.tools.base import ToolBusinessError, ToolContext, ToolDefinition


async def list_files(args: dict, ctx: ToolContext) -> dict:
    repo_id = args.get("repo_id") or (ctx.repo_ids[0] if ctx.repo_ids else None)
    if not repo_id:
        raise ToolBusinessError("需要指定 repo_id，或先在会话中关联仓库")
    repo = await get_repo(str(repo_id), ctx.user["id"])
    if not repo:
        raise ToolBusinessError("仓库不存在或无权访问")

    prefix = str(args.get("path_prefix") or "").strip().rstrip("/")
    limit = min(max(int(args.get("limit") or 200), 1), 500)

    from app.db import query
    sql = "SELECT path, language, size, line_count, is_doc FROM repo_files WHERE repo_id = %s"
    params: list = [str(repo_id)]
    if prefix:
        sql += " AND path LIKE %s"
        params.append(f"{prefix}%")
    sql += " ORDER BY path LIMIT %s"
    params.append(limit)

    rows = await query(sql, tuple(params))
    return {
        "repo": repo["name"],
        "count": len(rows),
        "files": [
            {"path": r[0], "language": r[1] or "", "size": r[2] or 0,
             "lines": r[3] or 0, "is_doc": bool(r[4])}
            for r in rows
        ],
    }


TOOL = ToolDefinition(
    name="list_files",
    description=(
        "列出仓库中的文件（可按目录前缀过滤）。用于确定要读/改哪些文件；"
        "文件较多时先用它缩小范围，再配合 search_code。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "path_prefix": {"type": "string", "description": "目录或文件前缀，如 app/ 或 tests/"},
            "repo_id": {"type": "string", "description": "仓库 UUID（可选，默认取会话关联仓库）"},
            "limit": {"type": "integer", "description": "最多返回条数（默认 200，上限 500）"},
        },
        "required": [],
    },
    func=list_files,
    category="read",
    timeout=20,
)
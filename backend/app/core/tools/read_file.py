"""read_file tool: read exact file content (paged) before editing."""
from app.core.indexing.pipeline import get_repo
from app.core.security.paths import UnsafePathError, normalize_relpath, resolve_repo_path
from app.core.tools.base import ToolBusinessError, ToolContext, ToolDefinition

MAX_LINES = 2000
MAX_CHARS = 200_000


async def read_file(args: dict, ctx: ToolContext) -> dict:
    path = str(args.get("path") or "").strip().replace("\\", "/")
    if not path:
        raise ToolBusinessError("path 不能为空")
    repo_id = args.get("repo_id") or (ctx.repo_ids[0] if ctx.repo_ids else None)
    if not repo_id:
        raise ToolBusinessError("需要指定 repo_id，或先在会话中关联仓库")

    repo = await get_repo(str(repo_id), ctx.user["id"])
    if not repo:
        raise ToolBusinessError("仓库不存在或无权访问")

    try:
        rel = normalize_relpath(path)
        target = resolve_repo_path(repo["root_path"], rel)
    except UnsafePathError as exc:
        raise ToolBusinessError(str(exc))
    if not target.is_file():
        raise ToolBusinessError(f"文件不存在：{rel}")

    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise ToolBusinessError(f"读取失败：{exc}")

    lines = content.splitlines()
    start = max(1, int(args.get("start_line") or 1))
    end = int(args.get("end_line") or len(lines) or 1)
    end = min(max(end, start), len(lines) or 1, start + MAX_LINES - 1)

    selected = "\n".join(lines[start - 1:end])[:MAX_CHARS]
    return {
        "path": rel,
        "total_lines": len(lines),
        "start_line": start,
        "end_line": end,
        "truncated": end < len(lines),
        "content": selected,
    }


TOOL = ToolDefinition(
    name="read_file",
    description=(
        "读取仓库中某个文件的精确内容（可按行分页，默认最多 2000 行）。"
        "修改文件前必须先读原文，不要凭记忆或检索片段猜测。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件相对路径，如 app/main.py"},
            "repo_id": {"type": "string", "description": "仓库 UUID（可选，默认取会话关联仓库）"},
            "start_line": {"type": "integer", "description": "起始行（从 1 开始，可选）"},
            "end_line": {"type": "integer", "description": "结束行（可选）"},
        },
        "required": ["path"],
    },
    func=read_file,
    category="read",
    timeout=20,
)
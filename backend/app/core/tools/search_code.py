"""search_code tool: symbol lookup + hybrid retrieval with file:line results."""
import uuid

from app.core.indexing.symbols import search_symbols
from app.core.rag.retriever import retrieve
from app.core.tools.base import ToolBusinessError, ToolContext, ToolDefinition


async def search_code(args: dict, ctx: ToolContext) -> dict:
    query = (args.get("query") or "").strip()
    if not query:
        raise ToolBusinessError("query 不能为空")

    repo_id = args.get("repo_id")
    if repo_id:
        try:
            uuid.UUID(str(repo_id))
        except ValueError:
            raise ToolBusinessError(
                "repo_id 必须是 UUID。通常无需传它：关联了仓库的会话默认就在该仓库检索。"
            )
        from app.core.indexing.pipeline import get_repo
        if not await get_repo(str(repo_id), ctx.user["id"]):
            raise ToolBusinessError("仓库不存在或无权访问")
        repo_ids = [str(repo_id)]
    elif ctx.repo_ids:
        repo_ids = list(ctx.repo_ids)
    else:
        raise ToolBusinessError("请先在会话中关联至少一个仓库，或显式传入 repo_id")

    symbols = await search_symbols(query, repo_ids, limit=6)

    snippets = []
    hits = await retrieve(query, top_k=8, repo_ids=repo_ids, user_id=ctx.user["id"])
    for h in hits:
        snippets.append({
            "path": h.path,
            "line_start": h.line_start,
            "line_end": h.line_end,
            "source": h.score_type,
            "content": h.content[:400],
        })

    if not symbols and not snippets:
        return {
            "symbols": [],
            "snippets": [],
            "note": "未命中。确认目标仓库已被导入并索引完成（Workspace 页面可查看状态），或换用更具体的关键词/函数名再试。",
        }

    return {"symbols": symbols, "snippets": snippets}


TOOL = ToolDefinition(
    name="search_code",
    description=(
        "在已索引的仓库中检索代码：按符号名（函数/类/接口）精确查找，并做混合语义检索。"
        "返回结果带 文件路径与行号，可直接作为回答引用。回答“X 在哪实现/怎么写的”之前应先调用本工具。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "要查找的内容：函数名、类名、关键词或自然语言描述"},
            "repo_id": {"type": "string", "description": "限定某个仓库（可选；默认检索当前对话选中的仓库）"},
        },
        "required": ["query"],
    },
    func=search_code,
    timeout=30,
)
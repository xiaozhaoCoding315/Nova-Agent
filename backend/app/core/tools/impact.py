"""impact_analysis tool: what breaks if this symbol/file changes?"""
import uuid

from app.core.impact.analysis import analyze_impact
from app.core.tools.base import ToolBusinessError, ToolContext, ToolDefinition


async def impact_analysis(args: dict, ctx: ToolContext) -> dict:
    query = (args.get("query") or "").strip()
    if not query:
        raise ToolBusinessError("query 不能为空：填入函数名、类名或文件路径")

    repo_id = args.get("repo_id")
    if repo_id:
        try:
            uuid.UUID(str(repo_id))
        except ValueError:
            raise ToolBusinessError("repo_id 必须是 UUID（会话已关联仓库时通常可省略）")
        from app.core.indexing.pipeline import get_repo
        if not await get_repo(str(repo_id), ctx.user["id"]):
            raise ToolBusinessError("仓库不存在或无权访问")
    elif ctx.repo_ids:
        repo_id = ctx.repo_ids[0]
    else:
        raise ToolBusinessError("需要先在会话中关联至少一个仓库，或显式传 repo_id")

    return await analyze_impact(str(repo_id), query, depth=max(1, min(int(args.get("depth", 2)), 3)))


TOOL = ToolDefinition(
    name="impact_analysis",
    description=(
        "变更影响分析：给定函数/类/文件，基于导入依赖图与符号引用，返回直接/间接依赖文件、"
        "引用位置、相关测试与风险等级，可建议应运行的测试命令。"
        "用户问「改这个会影响什么」「动这个安全吗」时使用。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "符号名（函数/类）或文件路径"},
            "repo_id": {"type": "string", "description": "仓库 UUID（可选，默认取会话关联仓库）"},
            "depth": {"type": "integer", "description": "传递依赖深度，1-3，默认 2"},
        },
        "required": ["query"],
    },
    func=impact_analysis,
    timeout=30,
)
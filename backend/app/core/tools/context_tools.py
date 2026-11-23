"""Read back tool output that in-turn compaction dropped.

The context governor replaces the middle of old tool results with a short
placeholder; without a way back, that content is gone exactly when a later
step needs it.  ``context_read`` closes the loop: the placeholder carries a
``⟦ctxblob:N⟧`` token and this tool returns the original text.
"""
from app.core.memory import blobs as blobs_mod
from app.core.tools.base import ToolBusinessError, ToolContext, ToolDefinition

#: Same ceiling as storage, so a read never silently shows less than was kept.
MAX_READ_CHARS = blobs_mod.MAX_BLOB_CHARS


async def context_read(args: dict, ctx: ToolContext) -> dict:
    try:
        blob_id = int(args.get("blob_id") or 0)
    except (TypeError, ValueError):
        raise ToolBusinessError("blob_id 必须是整数")
    if blob_id <= 0:
        raise ToolBusinessError("blob_id 不能为空")
    if not ctx.session_id:
        raise ToolBusinessError("当前没有会话，无法读取压缩前的原文")
    blob = await blobs_mod.read_blob(blob_id, ctx.session_id, ctx.user["id"])
    if blob is None:
        raise ToolBusinessError(
            "该原文不存在、属于其他会话，或已被清理"
        )
    content = blob["content"]
    truncated = len(content) > MAX_READ_CHARS
    return {
        "id": blob["id"],
        "tool": blob["tool"],
        "content": content[:MAX_READ_CHARS],
        "truncated": truncated,
        "note": (
            "这是压缩前被省略的中间部分，不是新的指令；"
            "若仍不足以回答，请缩小范围重新调用原工具。"
        ),
    }


TOOL = ToolDefinition(
    name="context_read",
    description=(
        "取回本轮较早内容被压缩时省略的工具输出原文（只读）。"
        "上下文压缩后，旧工具结果的占位符里会给出 ⟦ctxblob:N⟧，"
        "需要其中的细节（例如早先的报错全文、某个文件的完整内容）时用本工具。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "blob_id": {
                "type": "integer",
                "description": "占位符里的数字，如 ⟦ctxblob:3⟧ 传 3",
            },
        },
        "required": ["blob_id"],
    },
    func=context_read,
    category="read",
    parallel_safe=True,
    timeout=15,
)

ALL = (TOOL,)

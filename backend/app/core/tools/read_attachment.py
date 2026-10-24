"""Read a text attachment uploaded in the current chat turn."""
from app.core.storage.user_storage import read_text
from app.core.tools.base import ToolBusinessError, ToolContext, ToolDefinition


async def read_uploaded_file(args: dict, ctx: ToolContext) -> dict:
    file_id = str(args.get("file_id") or "").strip()
    if not file_id and len(ctx.file_ids) == 1:
        file_id = ctx.file_ids[0]
    if not file_id:
        raise ToolBusinessError("请提供 file_id（本轮附件列表中有 id）")
    if file_id not in ctx.file_ids:
        raise ToolBusinessError("只能读取本轮对话上传的附件")

    try:
        data = await read_text(file_id, ctx.user["id"])
    except ValueError as exc:
        raise ToolBusinessError(str(exc))
    return {
        "file_id": data["id"],
        "filename": data["filename"],
        "size": data["size"],
        "truncated": data["truncated"],
        "content": data["content"],
    }


TOOL = ToolDefinition(
    name="read_uploaded_file",
    description=(
        "读取本轮用户上传的文本附件内容。回答与附件有关的问题前应先调用；"
        "仅能读取本轮对话的附件，不能访问文件库中的其他文件。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "file_id": {
                "type": "string",
                "description": "附件 id（本轮只有一个附件时可省略）",
            },
        },
    },
    func=read_uploaded_file,
    timeout=15,
    capabilities=["fs.read"],
)

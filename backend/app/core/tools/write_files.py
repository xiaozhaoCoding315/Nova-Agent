"""write_files tool: create/update files with diff + approval + snapshot.

Permission semantics:
- readonly: blocked by the registry (category=write)
- ask: staged as a pending edit; nothing is written until the user approves
- auto: written immediately, with the pre-write snapshot kept for revert
"""
from app.core.editing.service import create_edit
from app.core.tools.base import ToolBusinessError, ToolContext, ToolDefinition


async def write_files(args: dict, ctx: ToolContext) -> dict:
    repo_id = args.get("repo_id") or (ctx.repo_ids[0] if ctx.repo_ids else None)
    if not repo_id:
        raise ToolBusinessError("需要指定 repo_id，或先在会话中关联仓库")

    files = args.get("files")
    if not isinstance(files, dict) or not files:
        raise ToolBusinessError("files 必须是非空对象：{相对路径: 完整文件内容}")

    try:
        edit = await create_edit(
            user_id=ctx.user["id"],
            session_id=ctx.session_id or None,
            repo_id=str(repo_id),
            files=files,
            note=str(args.get("note") or ""),
            mode=ctx.permission_mode,
        )
    except ValueError as exc:
        raise ToolBusinessError(str(exc))

    if edit["staged"]:
        return {
            "edit_id": edit["id"],
            "staged": True,
            "status": "pending",
            "files": edit["files"],
            "diff_preview": edit["diff"][:4000],
            "hint": "已生成待审批修改。尚未写入磁盘，请告知用户到界面点击「批准修改」。",
        }

    return {
        "edit_id": edit["id"],
        "staged": False,
        "status": "applied",
        "files": edit["files"],
        "diff_preview": edit["diff"][:4000],
        "hint": "已写入工作区（快照可用于撤销），索引将自动重建。",
    }


TOOL = ToolDefinition(
    name="write_files",
    description=(
        "创建或修改仓库文件：{相对路径: 完整文件内容}（不是 diff，必须给整份文件）。"
        "会自动生成 diff 并保存修改前快照；在「确认」模式下只生成待审批提案，批准后才写入；"
        "「自动」模式直接写入；只读模式会被拒绝。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "files": {
                "type": "object",
                "description": "要写入的文件：{相对路径: 完整文件内容}，例如 {\"app/main.py\": \"...\"}",
            },
            "repo_id": {"type": "string", "description": "仓库 UUID（可选，默认取会话关联仓库）"},
            "note": {"type": "string", "description": "本次修改的说明（可选）"},
        },
        "required": ["files"],
    },
    func=write_files,
    category="write",
    timeout=30,
)
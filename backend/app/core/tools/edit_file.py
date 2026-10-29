"""edit_file tool: exact-match replacements on an existing repo file.

The tool reuses ``create_edit`` so diff preview, approval gating, snapshots,
conflict detection and test-preservation checks are identical to write_files.
"""
import difflib

from app.core.editing.service import MAX_FILE_CHARS, create_edit
from app.core.indexing.pipeline import get_repo
from app.core.security.paths import (
    UnsafePathError, normalize_relpath, resolve_repo_path,
)
from app.core.tools.base import ToolBusinessError, ToolContext, ToolDefinition

MAX_EDITS = 20
MAX_MATCH_CHARS = 100_000


def _not_found_message(content: str, old: str, index: int) -> str:
    first_line = old.splitlines()[0] if old.splitlines() else old
    lines = content.splitlines()
    close = difflib.get_close_matches(first_line, lines, n=3, cutoff=0.4)
    hint = ""
    if close:
        numbered = []
        for match in close:
            line_no = lines.index(match) + 1
            numbered.append(f"第 {line_no} 行：{match.strip()[:120]}")
        hint = "\n最相似的行：\n" + "\n".join(numbered)
    return (
        f"第 {index} 条 edit：未找到 old_string。"
        "old_string 必须与文件内容逐字一致（含缩进）；请先调用 read_file 确认原文。"
        + hint
    )


def _apply_edits(content: str, edits: list[dict]) -> tuple[str, int]:
    total = 0
    for index, edit in enumerate(edits, 1):
        if not isinstance(edit, dict):
            raise ToolBusinessError(f"第 {index} 条 edit 必须是对象")
        old = edit.get("old_string")
        new = edit.get("new_string")
        replace_all = edit.get("replace_all", False)
        if not isinstance(replace_all, bool):
            raise ToolBusinessError(f"第 {index} 条 edit 的 replace_all 必须是布尔值")
        if not isinstance(old, str) or not old:
            raise ToolBusinessError(f"第 {index} 条 edit 的 old_string 必须是非空字符串")
        if not isinstance(new, str):
            raise ToolBusinessError(f"第 {index} 条 edit 的 new_string 必须是字符串")
        if len(old) > MAX_MATCH_CHARS or len(new) > MAX_MATCH_CHARS:
            raise ToolBusinessError(f"第 {index} 条 edit 的 old_string/new_string 过大")
        occurrences = content.count(old)
        if occurrences == 0:
            raise ToolBusinessError(_not_found_message(content, old, index))
        if occurrences > 1 and not replace_all:
            raise ToolBusinessError(
                f"第 {index} 条 edit：old_string 匹配到 {occurrences} 处，"
                "请补充上下文使其唯一，或设置 replace_all=true"
            )
        if replace_all:
            content = content.replace(old, new)
            total += occurrences
        else:
            content = content.replace(old, new, 1)
            total += 1
    return content, total


async def edit_file(args: dict, ctx: ToolContext) -> dict:
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
        raise ToolBusinessError(f"文件不存在：{rel}；新建文件请用 write_files")
    try:
        if target.stat().st_size > MAX_FILE_CHARS * 4:
            raise ToolBusinessError(
                f"文件超过 {MAX_FILE_CHARS * 4} 字节，edit_file 不支持超大文件"
            )
    except OSError as exc:
        raise ToolBusinessError(f"读取失败：{exc}")

    edits = args.get("edits")
    if not isinstance(edits, list) or not edits:
        raise ToolBusinessError("edits 必须是非空数组")
    if len(edits) > MAX_EDITS:
        raise ToolBusinessError(f"单次最多 {MAX_EDITS} 条 edit")

    content = target.read_text(encoding="utf-8", errors="replace")
    updated, occurrences = _apply_edits(content, edits)
    if updated == content:
        raise ToolBusinessError("没有实际改动")
    if len(updated) > MAX_FILE_CHARS:
        raise ToolBusinessError(
            f"编辑后的文件超过 {MAX_FILE_CHARS} 字符上限；edit_file 不支持超大文件，请拆分"
        )

    try:
        edit = await create_edit(
            user_id=ctx.user["id"],
            session_id=ctx.session_id or None,
            repo_id=str(repo_id),
            files={rel: updated},
            note=str(args.get("note") or ""),
            mode=ctx.permission_mode,
        )
    except ValueError as exc:
        raise ToolBusinessError(str(exc))

    return {
        "edit_id": edit["id"],
        "staged": edit["staged"],
        "status": edit["status"],
        "files": edit["files"],
        "diff_preview": edit["diff"][:4000],
        "occurrences": occurrences,
        "hint": (
            "已生成待审批修改。尚未写入磁盘，请告知用户到界面点击「批准修改」。"
            if edit["staged"] else
            "已写入工作区（快照可用于撤销），索引将自动重建。"
        ),
    }


TOOL = ToolDefinition(
    name="edit_file",
    description=(
        "对仓库中已存在的文件做精确替换编辑。old_string 必须与原文逐字一致（含缩进），"
        "默认要求唯一匹配；需要替换多处时设 replace_all=true。"
        "已存在文件的小改动优先用本工具；新建文件或整文件重写用 write_files。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件相对路径，如 src/auth.py"},
            "edits": {
                "type": "array",
                "description": "按顺序应用的替换列表",
                "items": {
                    "type": "object",
                    "properties": {
                        "old_string": {
                            "type": "string",
                            "description": "原文片段，必须逐字一致（含缩进）",
                        },
                        "new_string": {
                            "type": "string",
                            "description": "替换后的内容；空字符串表示删除该片段",
                        },
                        "replace_all": {
                            "type": "boolean",
                            "description": "为 true 时替换全部匹配（默认 false）",
                        },
                    },
                    "required": ["old_string", "new_string"],
                },
            },
            "repo_id": {"type": "string", "description": "仓库 UUID（可选，默认取会话关联仓库）"},
            "note": {"type": "string", "description": "本次修改的说明（可选）"},
        },
        "required": ["path", "edits"],
    },
    func=edit_file,
    category="write",
    capabilities=["fs.write"],
    timeout=30,
)

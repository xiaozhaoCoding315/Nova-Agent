"""Document workspace endpoints: Markdown manuscripts, versions, exports."""
from __future__ import annotations

import asyncio
import mimetypes
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from app.config import settings
from app.core.documents import workspace as ws
from app.core.documents.store import (
    create_user_workspace,
    get_workspace,
    list_workspaces,
    remove_workspace,
)
from app.core.security.auth import get_current_user
from app.core.security.limits import ensure_token_budget
from app.core.documents.convert import ConversionError, convert_document
from app.models.schemas import (
    DocumentConvertIn,
    DocumentConvertOut,
    DocumentContentOut,
    DocumentDiagnosticsOut,
    DocumentDraftIn,
    DocumentDraftOut,
    DocumentExportIn,
    DocumentExportOut,
    DocumentFileListOut,
    DocumentFileOut,
    DocumentRestoreIn,
    DocumentVersionListOut,
    DocumentVersionOut,
    DocumentWorkspaceIn,
    DocumentWorkspaceListOut,
    DocumentWorkspaceOut,
    DocumentWriteIn,
    DocumentWriteOut,
    OkOut,
)

router = APIRouter(prefix="/documents")

DRAFT_SYSTEM_PROMPT = """你负责起草一份普通报告，输出可直接编辑的中文 Markdown。

规则：
1. 只使用用户给出的主题、范围与已知事实；缺少的数据、姓名、机构、日期、统计值一律写成「待补充」，不得编造。
2. 句子具体、平实；不用夸张、营销、拟人化措辞，不写重复的套话与机械过渡。
3. 从一级标题开始，按需要分节；不要输出解释、寒暄，也不要用代码围栏包住整篇文档。
4. 用户给字数要求时按中文字符数控制篇幅；没给就按内容需要写，不硬凑字数。
5. 这是报告，不是学位论文；不要声称已经核实任何外部事实。"""


def _strip_fence(text: str) -> str:
    value = (text or "").strip()
    if value.startswith("```"):
        lines = value.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        value = "\n".join(lines).strip()
    return value


def _not_found(exc: Exception) -> HTTPException:
    return HTTPException(status_code=404, detail=str(exc))


def _conflict(exc: ws.WorkspaceConflict) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={"message": str(exc), "current_sha": exc.current_sha},
    )


def _bad_request(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


async def _call(func, *args, **kwargs):
    """Run blocking file work without stalling the event loop."""
    return await asyncio.to_thread(func, *args, **kwargs)


def _workspace_out(workspace: ws.Workspace) -> DocumentWorkspaceOut:
    return DocumentWorkspaceOut(
        id=workspace.id, title=workspace.title, kind=workspace.kind,
        created_at=workspace.created_at,
        root=str(workspace.root) if settings.is_local else None,
    )


def _version_out(version: ws.VersionInfo) -> DocumentVersionOut:
    return DocumentVersionOut(**version.to_dict())


@router.post("/workspaces", response_model=DocumentWorkspaceOut)
async def create_workspace(body: DocumentWorkspaceIn, user: dict = Depends(get_current_user)):
    try:
        workspace = await _call(
            create_user_workspace, user["id"],
            title=body.title, kind=body.kind, root=body.root,
            allow_custom_root=settings.is_local,
        )
    except ws.WorkspaceError as exc:
        raise _bad_request(exc) from exc
    return _workspace_out(workspace)


@router.get("/workspaces", response_model=DocumentWorkspaceListOut)
async def get_workspaces(user: dict = Depends(get_current_user)):
    try:
        items = await _call(list_workspaces, user["id"])
    except ws.WorkspaceError as exc:
        raise _bad_request(exc) from exc
    return DocumentWorkspaceListOut(
        workspaces=[DocumentWorkspaceOut(
            id=item["id"], title=item["title"], kind=item["kind"],
            created_at=item.get("created_at") or "",
            root=item.get("root") if settings.is_local else None,
        ) for item in items]
    )


@router.get("/workspaces/{workspace_id}", response_model=DocumentWorkspaceOut)
async def get_one_workspace(workspace_id: str, user: dict = Depends(get_current_user)):
    try:
        workspace = await _call(get_workspace, user["id"], workspace_id)
    except ws.WorkspaceNotFound as exc:
        raise _not_found(exc) from exc
    except ws.WorkspaceError as exc:
        raise _bad_request(exc) from exc
    return _workspace_out(workspace)


@router.delete("/workspaces/{workspace_id}", response_model=OkOut)
async def delete_workspace(workspace_id: str, user: dict = Depends(get_current_user)):
    try:
        removed = await _call(remove_workspace, user["id"], workspace_id)
    except ws.WorkspaceError as exc:
        raise _bad_request(exc) from exc
    if not removed:
        raise HTTPException(status_code=404, detail="文档工作区不存在")
    return OkOut()


@router.get("/workspaces/{workspace_id}/files", response_model=DocumentFileListOut)
async def list_files(workspace_id: str, user: dict = Depends(get_current_user)):
    try:
        workspace = await _call(get_workspace, user["id"], workspace_id)
        files = await _call(ws.list_manuscripts, workspace)
    except ws.WorkspaceNotFound as exc:
        raise _not_found(exc) from exc
    except ws.WorkspaceError as exc:
        raise _bad_request(exc) from exc
    return DocumentFileListOut(files=[DocumentFileOut(**item.to_dict()) for item in files])


@router.get("/workspaces/{workspace_id}/content", response_model=DocumentContentOut)
async def read_content(
    workspace_id: str,
    path: str = Query(min_length=1, max_length=500),
    user: dict = Depends(get_current_user),
):
    try:
        workspace = await _call(get_workspace, user["id"], workspace_id)
        content = await _call(ws.read_manuscript, workspace, path)
    except ws.WorkspaceNotFound as exc:
        raise _not_found(exc) from exc
    except ws.WorkspaceError as exc:
        raise _bad_request(exc) from exc
    return DocumentContentOut(**content)


@router.put("/workspaces/{workspace_id}/content", response_model=DocumentWriteOut)
async def write_content(
    workspace_id: str,
    body: DocumentWriteIn,
    user: dict = Depends(get_current_user),
):
    try:
        workspace = await _call(get_workspace, user["id"], workspace_id)
        result = await _call(
            ws.write_manuscript, workspace, body.path, body.content,
            base_sha=body.base_sha, force=body.force,
        )
    except ws.WorkspaceConflict as exc:
        raise _conflict(exc) from exc
    except ws.WorkspaceNotFound as exc:
        raise _not_found(exc) from exc
    except ws.WorkspaceError as exc:
        raise _bad_request(exc) from exc
    return DocumentWriteOut(
        path=result.path, sha256=result.sha256, created=result.created,
        version=_version_out(result.version) if result.version else None,
    )


@router.get("/workspaces/{workspace_id}/versions", response_model=DocumentVersionListOut)
async def get_versions(
    workspace_id: str,
    path: str = Query(min_length=1, max_length=500),
    user: dict = Depends(get_current_user),
):
    try:
        workspace = await _call(get_workspace, user["id"], workspace_id)
        versions = await _call(ws.list_versions, workspace, path)
    except ws.WorkspaceNotFound as exc:
        raise _not_found(exc) from exc
    except ws.WorkspaceError as exc:
        raise _bad_request(exc) from exc
    return DocumentVersionListOut(versions=[_version_out(item) for item in versions])


@router.post(
    "/workspaces/{workspace_id}/versions/{version_id}/restore",
    response_model=DocumentWriteOut,
)
async def restore(
    workspace_id: str,
    version_id: str,
    body: DocumentRestoreIn,
    user: dict = Depends(get_current_user),
):
    try:
        workspace = await _call(get_workspace, user["id"], workspace_id)
        result = await _call(
            ws.restore_version, workspace, body.path, version_id, base_sha=body.base_sha,
        )
    except ws.WorkspaceConflict as exc:
        raise _conflict(exc) from exc
    except ws.WorkspaceNotFound as exc:
        raise _not_found(exc) from exc
    except ws.WorkspaceError as exc:
        raise _bad_request(exc) from exc
    return DocumentWriteOut(
        path=result.path, sha256=result.sha256, created=result.created,
        version=_version_out(result.version) if result.version else None,
    )


@router.post("/workspaces/{workspace_id}/draft", response_model=DocumentDraftOut)
async def draft_report(
    workspace_id: str,
    body: DocumentDraftIn,
    user: dict = Depends(get_current_user),
):
    """Draft an ordinary report from requirements into a new Markdown file.

    Thesis and resume workspaces are deliberately excluded: a thesis needs the
    staged, author-confirmed flow (M3), and a resume may only reorganize facts.
    """
    try:
        workspace = await _call(get_workspace, user["id"], workspace_id)
    except ws.WorkspaceNotFound as exc:
        raise _not_found(exc) from exc
    except ws.WorkspaceError as exc:
        raise _bad_request(exc) from exc
    if workspace.kind != "report":
        raise HTTPException(
            status_code=400,
            detail="只有报告工作区支持从需求直接起草；论文请用写作对话，简历只能用已确认的事实。",
        )
    relative, path = ws.resolve_manuscript_path(workspace, body.path)
    if path.exists():
        raise HTTPException(status_code=409, detail="目标正文已存在，请换一个文件名或先清空该文件。")

    await ensure_token_budget(user)
    from app.core.llm.factory import get_llm

    try:
        llm = await get_llm(user["id"], purpose="write")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"模型不可用：{str(exc)[:200]}") from exc

    instruction = body.requirements.strip()
    if body.word_count:
        instruction += f"\n\n目标篇幅：约 {body.word_count} 个中文字符。"
    messages = [
        {"role": "system", "content": DRAFT_SYSTEM_PROMPT},
        {"role": "user", "content": f"报告要求：\n{instruction}\n\n文件名：{relative}"},
    ]
    parts: list[str] = []
    usage: dict | None = None
    try:
        async with asyncio.timeout(settings.llm_timeout):
            async for event in llm.astream_with_tools(messages, []):
                if isinstance(event, str):
                    parts.append(event)
                elif event.get("type") == "content":
                    parts.append(event.get("content") or "")
                elif event.get("type") == "usage":
                    value = event.get("usage")
                    if isinstance(value, dict):
                        usage = value
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"起草失败：{str(exc)[:200]}") from exc

    content = _strip_fence("".join(parts))
    if not content.strip():
        raise HTTPException(status_code=502, detail="模型没有返回正文，未写入文件。")
    try:
        result = await _call(ws.write_manuscript, workspace, relative, content)
    except ws.WorkspaceConflict as exc:
        raise _conflict(exc) from exc
    except ws.WorkspaceError as exc:
        raise _bad_request(exc) from exc

    if usage:
        from app.core.llm.usage import record_usage

        await record_usage(user["id"], None, usage, source="documents")
    return DocumentDraftOut(
        path=result.path, sha256=result.sha256, content=content, usage=usage,
    )


@router.post("/workspaces/{workspace_id}/convert", response_model=DocumentConvertOut)
async def convert_workspace_file(
    workspace_id: str,
    body: DocumentConvertIn,
    user: dict = Depends(get_current_user),
):
    """Convert a file inside one workspace into DOCX/PDF.

    The source must already be inside the workspace.  Outputs go to
    ``exports/`` and a fidelity sidecar is written next to each artifact.
    """
    try:
        workspace = await _call(get_workspace, user["id"], workspace_id)
    except ws.WorkspaceNotFound as exc:
        raise _not_found(exc) from exc
    except ws.WorkspaceError as exc:
        raise _bad_request(exc) from exc
    root = workspace.root.resolve()
    source = (root / body.source_path).resolve()
    try:
        source.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="源文件必须位于工作区内") from exc
    if not source.is_file():
        raise HTTPException(status_code=404, detail="源文件不存在")
    try:
        result = await _call(
            convert_document,
            source,
            body.target_format,
            root / ws.EXPORT_DIR,
            profile=body.profile,
            overwrite=body.overwrite,
            allow_lossy=body.allow_lossy,
        )
    except ConversionError as exc:
        raise _bad_request(exc) from exc
    data = result.to_dict()
    for key in ("output_path", "fidelity_path"):
        value = data.get(key)
        if value:
            try:
                relative = Path(value).resolve().relative_to(root)
                data[key] = relative.as_posix()
            except ValueError:
                data[key] = Path(value).name
    return DocumentConvertOut(**data)


@router.post("/workspaces/{workspace_id}/export", response_model=DocumentExportOut)
async def export(
    workspace_id: str,
    body: DocumentExportIn,
    user: dict = Depends(get_current_user),
):
    try:
        workspace = await _call(get_workspace, user["id"], workspace_id)
        result = await _call(ws.export_manuscript, workspace, body.path, body.format)
    except ws.WorkspaceNotFound as exc:
        raise _not_found(exc) from exc
    except ws.WorkspaceError as exc:
        raise _bad_request(exc) from exc
    return DocumentExportOut(**result.to_dict())


@router.get("/workspaces/{workspace_id}/download")
async def download_export(
    workspace_id: str,
    path: str = Query(min_length=1, max_length=500),
    user: dict = Depends(get_current_user),
):
    """Download an export artifact.  Only files under ``exports/`` are served."""
    try:
        workspace = await _call(get_workspace, user["id"], workspace_id)
    except ws.WorkspaceNotFound as exc:
        raise _not_found(exc) from exc
    except ws.WorkspaceError as exc:
        raise _bad_request(exc) from exc
    relative = (path or "").replace("\\", "/").lstrip("/")
    parts = [part for part in relative.split("/") if part not in ("", ".")]
    if not parts or parts[0] != ws.EXPORT_DIR or any(part == ".." for part in parts):
        raise HTTPException(status_code=400, detail="只能下载 exports/ 下的导出文件")
    if Path(parts[-1]).suffix.lower() not in (".docx", ".pdf", ".json"):
        raise HTTPException(status_code=400, detail="不支持的导出文件类型")
    target = (workspace.root / "/".join(parts)).resolve()
    try:
        target.relative_to(workspace.root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="文件路径不能跳出工作区") from exc
    if not target.is_file():
        raise HTTPException(status_code=404, detail="导出文件不存在")
    return FileResponse(
        target,
        filename=target.name,
        media_type=mimetypes.guess_type(target.name)[0] or "application/octet-stream",
    )


@router.get("/workspaces/{workspace_id}/diagnostics", response_model=DocumentDiagnosticsOut)
async def diagnostics(workspace_id: str, user: dict = Depends(get_current_user)):
    try:
        workspace = await _call(get_workspace, user["id"], workspace_id)
        result = await _call(ws.workspace_diagnostics, workspace)
    except ws.WorkspaceNotFound as exc:
        raise _not_found(exc) from exc
    except ws.WorkspaceError as exc:
        raise _bad_request(exc) from exc
    return DocumentDiagnosticsOut(**result)

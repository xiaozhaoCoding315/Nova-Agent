"""Workspace endpoints: import / list / inspect / search indexed repos."""
import asyncio
import re
import shutil
import uuid
from pathlib import Path
import zipfile

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from app.config import settings
from app.core.indexing.pipeline import (
    create_repo_row,
    delete_repo,
    get_repo,
    list_repos,
    set_status,
)
from app.core.indexing.symbols import search_symbols
from app.core.indexing.walker import clone_git, safe_extract_zip
from app.core.jobs.service import enqueue_index
from app.core.rag.retriever import retrieve
from app.core.security.audit import AuditAction, log_audit
from app.core.security.auth import get_current_user
from app.core.security.limits import check_job_quota, check_search_quota
from app.core.security.paths import UnsafePathError, normalize_relpath, resolve_repo_path
from app.core.security.redaction import redact_text
from app.core.storage.user_storage import repo_container
from app.db import query as db_query
from app.models.schemas import (
    BrainOut,
    DebtReportOut,
    DebtSnapshotOut,
    FileContentOut,
    FileNodeOut,
    ImpactOut,
    OkOut,
    RepoImportGit,
    RepoOut,
    SearchHitOut,
    SearchResponseOut,
    StatusActionOut,
)

router = APIRouter()

MAX_FILE_VIEW_BYTES = 200_000


def _display_name(filename: str) -> str:
    name = re.sub(r"\.zip$", "", filename, flags=re.IGNORECASE)
    return name.strip() or "upload"


@router.post("/repos/upload", response_model=RepoOut)
async def upload_repo(file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    check_job_quota(user, "import")
    repo_id = str(uuid.uuid4())
    dest_root = repo_container(user["id"], repo_id)
    dest_root.mkdir(parents=True, exist_ok=True)
    tmp_zip = dest_root / "_upload.zip"

    total = 0
    max_bytes = settings.max_upload_mb * 1024 * 1024
    try:
        with open(tmp_zip, "wb") as out:
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if total > max_bytes:
                    raise HTTPException(status_code=413, detail=f"压缩包超过上限（{settings.max_upload_mb}MB）")
                out.write(chunk)

        src_dir = dest_root / "src"
        src_dir.mkdir(exist_ok=True)
        await asyncio.to_thread(
            safe_extract_zip,
            str(tmp_zip), str(src_dir),
            settings.max_repo_files, settings.max_file_kb * 1024,
        )
    except (zipfile.BadZipFile, ValueError) as exc:
        shutil.rmtree(dest_root, ignore_errors=True)
        raise HTTPException(status_code=400, detail=f"压缩包无效：{exc}")
    finally:
        tmp_zip.unlink(missing_ok=True)

    repo = await create_repo_row(user["id"], _display_name(file.filename or "upload"),
                                 f"zip:{file.filename}", repo_id)
    await enqueue_index(repo_id, user_id=user["id"])
    await log_audit(AuditAction.REPO_IMPORT, user_id=str(user["id"]),
                    details={"repo_id": repo_id, "source": "zip", "name": repo["name"]})
    return repo


@router.put("/repos/{repo_id}/files", response_model=RepoOut)
async def replace_repo_files(
    repo_id: str,
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
):
    """Replace the whole workspace from a zip (local bridge push). Re-indexes."""
    repo = await get_repo(repo_id, user["id"])
    if not repo:
        raise HTTPException(status_code=404, detail="仓库不存在")
    if repo["kind"] == "builder":
        raise HTTPException(status_code=400, detail="Builder 项目不能整仓替换")
    check_job_quota(user, "reindex")
    root = Path(repo["root_path"]).resolve()
    src_dir = root / "src"
    tmp_zip = root / "_bridge.zip"
    total = 0
    max_bytes = settings.max_upload_mb * 1024 * 1024
    try:
        with open(tmp_zip, "wb") as out:
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if total > max_bytes:
                    raise HTTPException(status_code=413, detail=f"压缩包超过上限（{settings.max_upload_mb}MB）")
                out.write(chunk)
        shutil.rmtree(src_dir, ignore_errors=True)
        src_dir.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(
            safe_extract_zip,
            str(tmp_zip), str(src_dir),
            settings.max_repo_files, settings.max_file_kb * 1024,
        )
    except (zipfile.BadZipFile, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"压缩包无效：{exc}")
    finally:
        tmp_zip.unlink(missing_ok=True)
    await enqueue_index(repo_id, reindex=True, user_id=user["id"])
    await log_audit(AuditAction.REPO_IMPORT, user_id=str(user["id"]),
                    details={"repo_id": repo_id, "source": "bridge", "name": repo["name"]})
    return await get_repo(repo_id, user["id"]) or repo


@router.post("/repos/git", response_model=RepoOut)
async def import_git_repo(body: RepoImportGit, user: dict = Depends(get_current_user)):
    check_job_quota(user, "import")
    repo_id = str(uuid.uuid4())
    dest = repo_container(user["id"], repo_id)
    dest.mkdir(parents=True, exist_ok=True)

    try:
        await clone_git(body.git_url, str(dest), settings.git_clone_timeout)
    except ValueError as exc:
        shutil.rmtree(dest, ignore_errors=True)
        raise HTTPException(status_code=400, detail=str(exc))

    name = body.name or body.git_url.rstrip("/").split("/")[-1].removesuffix(".git")
    repo = await create_repo_row(user["id"], name, f"git:{body.git_url}", repo_id)
    await enqueue_index(repo_id, user_id=user["id"])
    await log_audit(AuditAction.REPO_IMPORT, user_id=str(user["id"]),
                    details={"repo_id": repo_id, "source": "git", "url": body.git_url})
    return repo


@router.get("/repos", response_model=list[RepoOut])
async def get_repos(user: dict = Depends(get_current_user)):
    return await list_repos(user["id"])


@router.get("/repos/{repo_id}", response_model=RepoOut)
async def get_repo_detail(repo_id: str, user: dict = Depends(get_current_user)):
    repo = await get_repo(repo_id, user["id"])
    if not repo:
        raise HTTPException(status_code=404, detail="仓库不存在")
    return repo


@router.delete("/repos/{repo_id}", response_model=OkOut)
async def delete_repo_endpoint(repo_id: str, user: dict = Depends(get_current_user)):
    if not await delete_repo(repo_id, user["id"]):
        raise HTTPException(status_code=404, detail="仓库不存在")
    await log_audit(AuditAction.REPO_DELETE, user_id=str(user["id"]), details={"repo_id": repo_id})
    return {"ok": True}


@router.post("/repos/{repo_id}/reindex", response_model=StatusActionOut)
async def reindex(repo_id: str, user: dict = Depends(get_current_user)):
    repo = await get_repo(repo_id, user["id"])
    if not repo:
        raise HTTPException(status_code=404, detail="仓库不存在")
    check_job_quota(user, "reindex")
    await set_status(repo_id, "pending")
    await enqueue_index(repo_id, reindex=True, user_id=user["id"])
    return {"ok": True, "status": "pending"}


@router.get("/repos/{repo_id}/tree", response_model=list[FileNodeOut])
async def get_tree(repo_id: str, user: dict = Depends(get_current_user)):
    repo = await get_repo(repo_id, user["id"])
    if not repo:
        raise HTTPException(status_code=404, detail="仓库不存在")

    rows = await db_query(
        "SELECT path, size, language FROM repo_files WHERE repo_id = %s ORDER BY path",
        (repo_id,),
    )
    root: dict = {}
    for path, size, language in rows:
        node = root
        parts = path.split("/")
        for i, part in enumerate(parts):
            is_file = i == len(parts) - 1
            entry = node.setdefault(part, {"path": "/".join(parts[: i + 1]), "name": part,
                                           "type": "file" if is_file else "dir", "size": size if is_file else 0,
                                           "language": language if is_file else "", "children": {}})
            node = entry["children"]

    def to_nodes(mapping: dict) -> list[dict]:
        nodes = []
        for entry in sorted(mapping.values(), key=lambda e: (e["type"] == "file", e["name"])):
            children = to_nodes(entry["children"]) if entry["children"] else []
            nodes.append({**entry, "children": children})
        return nodes

    return to_nodes(root)


@router.get("/repos/{repo_id}/file", response_model=FileContentOut)
async def get_file(repo_id: str, path: str = Query(...), user: dict = Depends(get_current_user)):
    repo = await get_repo(repo_id, user["id"])
    if not repo:
        raise HTTPException(status_code=404, detail="仓库不存在")

    try:
        rel = normalize_relpath(path)
        target = resolve_repo_path(repo["root_path"], rel)
    except UnsafePathError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    rows = await db_query(
        "SELECT language, line_count, size FROM repo_files WHERE repo_id = %s AND path = %s",
        (repo_id, rel),
    )
    if not rows:
        raise HTTPException(status_code=404, detail="文件不存在")

    language, line_count, size = rows[0]
    if size > MAX_FILE_VIEW_BYTES:
        raise HTTPException(status_code=413, detail="文件过大，无法在线预览")

    if not target.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")

    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"读取失败：{exc}")

    return {"path": rel, "language": language or "", "line_count": line_count or 0, "content": content}


@router.get("/repos/{repo_id}/search", response_model=SearchResponseOut)
async def search_in_repo(
    repo_id: str,
    q: str = Query(..., min_length=1),
    user: dict = Depends(get_current_user),
):
    repo = await get_repo(repo_id, user["id"])
    if not repo:
        raise HTTPException(status_code=404, detail="仓库不存在")

    check_search_quota(user)
    symbols = await search_symbols(q, [repo_id], limit=8)
    hits = await retrieve(q, top_k=8, repo_ids=[repo_id], user_id=user["id"])
    return {
        "symbols": symbols,
        "hits": [
            SearchHitOut(
                path=h.path, line_start=h.line_start, line_end=h.line_end,
                content=redact_text(h.content[:400]), score=round(h.score, 3), source=h.score_type,
            ).model_dump()
            for h in hits
        ],
    }


@router.get("/repos/{repo_id}/impact", response_model=ImpactOut)
async def impact_in_repo(
    repo_id: str,
    q: str = Query(..., min_length=1),
    depth: int = Query(2, ge=1, le=3),
    user: dict = Depends(get_current_user),
):
    repo = await get_repo(repo_id, user["id"])
    if not repo:
        raise HTTPException(status_code=404, detail="仓库不存在")
    from app.core.impact.analysis import analyze_impact
    return await analyze_impact(repo_id, q, depth=depth)


@router.get("/repos/{repo_id}/brain", response_model=BrainOut)
async def repo_brain(repo_id: str, user: dict = Depends(get_current_user)):
    repo = await get_repo(repo_id, user["id"])
    if not repo:
        raise HTTPException(status_code=404, detail="仓库不存在")
    rows = await db_query("SELECT brain FROM repos WHERE id = %s", (repo_id,))
    return (rows[0][0] if rows else None) or {}


@router.get("/repos/{repo_id}/debt", response_model=DebtReportOut)
async def repo_debt(repo_id: str, user: dict = Depends(get_current_user)):
    repo = await get_repo(repo_id, user["id"])
    if not repo:
        raise HTTPException(status_code=404, detail="仓库不存在")
    from app.core.debt.service import get_report
    return await get_report(repo_id)


@router.post("/repos/{repo_id}/debt/scan", response_model=DebtSnapshotOut)
async def scan_repo_debt(repo_id: str, user: dict = Depends(get_current_user)):
    """Debt scan is cheap deterministic SQL — run inline, no job needed."""
    repo = await get_repo(repo_id, user["id"])
    if not repo:
        raise HTTPException(status_code=404, detail="仓库不存在")
    if repo["status"] != "ready":
        raise HTTPException(status_code=400, detail="仓库尚未完成索引")
    from app.core.debt.service import scan_repo
    metrics = await scan_repo(repo_id, user_id=user["id"])
    return DebtSnapshotOut(score=metrics["score"], metrics=metrics)
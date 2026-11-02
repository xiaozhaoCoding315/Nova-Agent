"""Per-user uploaded files: list, upload, download and delete."""
import io
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.config import settings
from app.core.agent.image_input import (
    VISION_MEDIA_TYPES,
    VISION_SUFFIXES,
    ImageRejected,
    validate_image_bytes,
)
from app.core.indexing.pipeline import get_repo
from app.core.memory import session as session_mod
from app.core.security.auth import get_current_user
from app.core.storage.user_storage import (
    delete_file,
    get_file,
    list_files,
    save_upload,
    storage_limit_bytes,
    used_bytes,
)
from app.models.schemas import FileListOut, FileOut, OkOut

router = APIRouter()

CLAIM_MEDIA_TYPES = VISION_MEDIA_TYPES | {"image/jpg"}


class _BufferedUpload:
    """Async read adapter so an in-memory image can reuse save_upload."""

    def __init__(self, data: bytes):
        self._buffer = io.BytesIO(data)

    async def read(self, size: int) -> bytes:
        return self._buffer.read(size)


async def _prepare_upload(file: UploadFile, purpose: str):
    claimed = (
        (file.content_type or "").lower() in CLAIM_MEDIA_TYPES
        or Path(file.filename or "").suffix.lower() in VISION_SUFFIXES
    )
    if purpose != "attachment" or not claimed:
        return file, file.content_type
    limit = settings.image_input_max_kb * 1024
    data = await file.read(limit + 1)
    try:
        info = validate_image_bytes(data)
    except ImageRejected as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _BufferedUpload(data), info.media_type


@router.get("/files", response_model=FileListOut)
async def get_files(
    repo_id: str | None = None,
    session_id: str | None = None,
    user: dict = Depends(get_current_user),
):
    files = await list_files(user["id"], repo_id=repo_id, session_id=session_id)
    return FileListOut(
        files=files,
        used_bytes=await used_bytes(user["id"]),
        limit_bytes=storage_limit_bytes(user),
    )


@router.post("/files", response_model=FileOut)
async def upload_file(
    file: UploadFile = File(...),
    repo_id: str | None = Form(default=None),
    session_id: str | None = Form(default=None),
    purpose: str = Form(default="attachment"),
    user: dict = Depends(get_current_user),
):
    if purpose not in ("attachment", "artifact", "import"):
        raise HTTPException(status_code=400, detail="无效的文件用途")
    if repo_id and not await get_repo(repo_id, user["id"]):
        raise HTTPException(status_code=404, detail="仓库不存在或无权访问")
    if session_id and not await session_mod.get_session(session_id, user["id"]):
        raise HTTPException(status_code=404, detail="会话不存在或无权访问")

    used = await used_bytes(user["id"])
    limit = storage_limit_bytes(user)
    announced = int(getattr(file, "size", 0) or 0)
    if announced and used + announced > limit:
        raise HTTPException(status_code=413, detail="个人存储空间不足")

    stream, mime = await _prepare_upload(file, purpose)
    try:
        saved = await save_upload(
            user["id"],
            stream,
            filename=file.filename or "file",
            mime=mime,
            repo_id=repo_id,
            session_id=session_id,
            purpose=purpose,
        )
    except ValueError as exc:
        raise HTTPException(status_code=413, detail=str(exc))

    if used + saved["size"] > limit:
        await delete_file(saved["id"], user["id"])
        raise HTTPException(status_code=413, detail="个人存储空间不足")
    return saved


@router.get("/files/{file_id}/download")
async def download_file(file_id: str, user: dict = Depends(get_current_user)):
    file = await get_file(file_id, user["id"])
    if not file:
        raise HTTPException(status_code=404, detail="文件不存在")
    path = Path(file["storage_path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="文件数据已丢失")
    return FileResponse(
        path,
        media_type=file["mime"],
        filename=file["filename"],
    )


@router.delete("/files/{file_id}", response_model=OkOut)
async def remove_file(file_id: str, user: dict = Depends(get_current_user)):
    if not await delete_file(file_id, user["id"]):
        raise HTTPException(status_code=404, detail="文件不存在")
    return {"ok": True}

"""桌面客户端安装包列表。

`/downloads` 页面本身由前端渲染（见 frontend/src/views/DownloadsView.tsx），
这里只提供数据。列表实时读目录：管理员把安装包放进 DOWNLOADS_DIR 后刷新
页面就能看到，不需要重启或重建镜像。
"""
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter

from app.config import settings
from app.models.schemas import DownloadFileOut, DownloadsOut

router = APIRouter()


def downloads_dir() -> Path:
    path = Path(settings.downloads_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def platform_label(filename: str) -> str:
    lower = filename.lower()
    if lower.endswith(".exe") or "windows" in lower or "win-" in lower:
        return "Windows"
    if lower.endswith(".dmg") or "macos" in lower or "darwin" in lower:
        return "macOS"
    if lower.endswith((".appimage", ".deb", ".rpm", ".tar.gz")):
        return "Linux"
    return "安装包"


@router.get("/downloads", response_model=DownloadsOut)
async def list_downloads() -> DownloadsOut:
    """公开接口：安装包下载不需要登录，与安装包直链一致。"""
    directory = downloads_dir()
    files = sorted(
        (path for path in directory.iterdir() if path.is_file() and not path.name.startswith(".")),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    items = []
    for path in files:
        stat = path.stat()
        items.append(
            DownloadFileOut(
                name=path.name,
                platform=platform_label(path.name),
                size=stat.st_size,
                modified_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
                url=f"/downloads/files/{urllib.parse.quote(path.name)}",
            )
        )
    hint = "" if items else f"管理员把安装包放进 {directory} 后刷新本页即可。"
    return DownloadsOut(files=items, directory=str(directory), hint=hint)

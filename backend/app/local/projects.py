"""Register an existing user folder as a project without copying it."""
import os
import uuid
from pathlib import Path

import structlog

from app.config import settings
from app.core.indexing.pipeline import create_local_repo_row, get_repo
from app.core.jobs.service import enqueue_index
from app.core.security.audit import AuditAction, log_audit
from app.db import query

logger = structlog.get_logger()


def validate_local_project_path(raw: str, data_root: Path) -> Path:
    text = (raw or "").strip()
    if not text or "\x00" in text:
        raise ValueError("项目路径不能为空")
    if text.startswith(("\\\\", "//")):
        raise ValueError("不支持 UNC/设备路径，请选择本机磁盘目录")
    if os.name == "nt" and text.startswith(("\\", "/")):
        raise ValueError("请输入绝对路径，例如 D:\\code\\my-project")
    path = Path(text).expanduser()
    if not path.is_absolute():
        raise ValueError("请输入项目目录的绝对路径")
    try:
        root = path.resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"目录不存在或无法访问：{text}") from exc
    if not root.is_dir():
        raise ValueError(f"不是目录：{text}")
    if root.parent == root:
        raise ValueError("不能直接打开磁盘根目录")
    data = data_root.expanduser().resolve()
    if data.exists() and not data.is_dir():
        raise ValueError(f"Nova 数据目录不是文件夹：{data}")
    if data.is_relative_to(root):
        raise ValueError(
            f"项目目录包含 Nova 数据目录（{data}），不能打开数据目录或其上级文件夹"
        )
    if root.is_relative_to(data):
        raise ValueError(f"不能打开 Nova 数据目录或其子目录：{data}")
    if not os.access(root, os.R_OK):
        raise ValueError("目录不可读，请检查 Windows 权限")
    return root


async def register_local_project(
    user: dict, raw_path: str, name: str | None = None
) -> dict:
    if not settings.is_local:
        raise ValueError("本地模式未启用")
    root = validate_local_project_path(raw_path, settings.data_root)
    rows = await query(
        "SELECT id FROM repos WHERE user_id = %s AND lower(root_path) = lower(%s) LIMIT 1",
        (user["id"], str(root)),
    )
    if rows:
        existing = await get_repo(str(rows[0][0]), user["id"])
        if existing:
            return existing
    repo_id = str(uuid.uuid4())
    display = (name or root.name).strip()[:200] or root.name
    repo = await create_local_repo_row(user["id"], display, str(root), repo_id)
    await enqueue_index(repo_id, user_id=user["id"])
    await log_audit(
        AuditAction.REPO_IMPORT,
        user_id=str(user["id"]),
        details={"repo_id": repo_id, "source": "local"},
    )
    logger.info("local_project_registered", repo_id=repo_id)
    return repo

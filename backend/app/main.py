import asyncio
import html
import time
import urllib.parse
from pathlib import Path

import structlog
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.api.v1.router import api_router
from app.core.logging_setup import setup_logging

logger = structlog.get_logger()

VERSION = "2.0.0"
_CLEANUP_INTERVAL_S = 3600


async def _cleanup_loop() -> None:
    """Hourly maintenance: long-term memory decay + TTL expiry."""
    while True:
        try:
            from app.core.memory.cleanup import run_cleanup
            summary = await run_cleanup()
            try:
                from app.core.deploy.service import cleanup_expired
                summary["previews_expired"] = await cleanup_expired()
            except Exception:
                logger.exception("preview_cleanup_failed")
            try:
                from app.core.account_cleanup import cleanup_expired_guests
                summary["guests_expired"] = await cleanup_expired_guests()
            except Exception:
                logger.exception("guest_cleanup_failed")
            try:
                from app.core.night.service import run_maintenance as night_maintenance
                summary["night_queue"] = await night_maintenance()
            except Exception:
                logger.exception("night_queue_failed")
            try:
                from app.core.debt.service import scan_stale_repos
                summary["debt_scanned"] = await scan_stale_repos()
            except Exception:
                logger.exception("debt_scan_failed")
            try:
                from app.core.reflection.service import extract_lessons
                summary["lessons_extracted"] = await extract_lessons()
            except Exception:
                logger.exception("reflection_failed")
            logger.info("cleanup_done", **summary)
        except ImportError:
            pass
        except Exception:
            logger.exception("cleanup_failed")
        await asyncio.sleep(_CLEANUP_INTERVAL_S)


@asynccontextmanager
async def lifespan(_: FastAPI):
    setup_logging()
    logger.info("nova_agent_starting", version=VERSION, env=settings.app_env)
    if settings.registration_mode not in ("open", "invite", "closed"):
        raise RuntimeError("REGISTRATION_MODE must be one of: open, invite, closed")
    if settings.app_env in ("prod", "production"):
        weak_secrets = {
            "change-me-in-production",
            "change-me-to-a-random-32-plus-char-string",
        }
        problems = []
        if len(settings.secret_key) < 32 or settings.secret_key in weak_secrets:
            problems.append("SECRET_KEY must be a random 32+ character value")
        if settings.admin_password in ("", "admin123"):
            problems.append("ADMIN_PASSWORD must be set to a strong value")
        if settings.demo_password in ("", "demo123"):
            problems.append("DEMO_PASSWORD must be set to a strong value")
        if problems:
            raise RuntimeError("insecure production configuration: " + "; ".join(problems))
    elif settings.secret_key == "change-me-in-production":
        logger.warning("weak_secret_key", hint="set SECRET_KEY to a random 32+ char string")
    if settings.auto_init_db:
        try:
            from app.db.init_db import init_all
            result = await init_all()
            logger.info("db_init_done", **{k: str(v)[:120] for k, v in result.items()})
        except Exception:
            logger.exception("db_init_failed_continuing_startup")
    task = asyncio.create_task(_cleanup_loop())
    job_runner = None
    if settings.job_runner_enabled:
        from app.core.jobs.runner import runner
        try:
            await runner.start()
            job_runner = runner
        except Exception:
            logger.exception("job_runner_start_failed_continuing_startup")
    mcp_service = None
    if settings.mcp_enabled:
        from app.core.mcp.manager import manager as mcp_service
        try:
            await mcp_service.start()
            from app.core.tools import get_registry
            registry = get_registry()
            for tool in mcp_service.tool_definitions():
                if registry.get(tool.name) is None:
                    registry.register(tool)
            logger.info("mcp_tools_registered", tools=mcp_service.tool_names())
        except Exception:
            logger.exception("mcp_start_failed_continuing_startup")
            mcp_service = None
    yield
    if mcp_service is not None:
        try:
            await mcp_service.stop()
        except Exception:
            logger.exception("mcp_stop_failed")
    if job_runner is not None:
        try:
            await job_runner.stop()
        except Exception:
            logger.exception("job_runner_stop_failed")
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    logger.info("nova_agent_shutting_down")


app = FastAPI(title="Nova Agent", version=VERSION, lifespan=lifespan)


@app.middleware("http")
async def request_logging(request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000
    if request.url.path.startswith("/api/v1"):
        logger.info(
            "request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=round(duration_ms, 1),
        )
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")

# ---------- 桌面客户端安装包下载 ----------
# 运维把安装包（如 Nova-Agent-Setup-2.0.0.exe）放进 DOWNLOADS_DIR 后，用户即可在
# 登录页点「下载桌面客户端」或直接访问 /downloads 获取；无需认证。
_DOWNLOADS_DIR = Path(settings.downloads_dir)
_DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)


def _human_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{size} B"
        size /= 1024
    return f"{size:.1f} GB"


@app.get("/downloads", response_class=HTMLResponse, include_in_schema=False)
@app.get("/downloads/", response_class=HTMLResponse, include_in_schema=False)
async def downloads_page() -> HTMLResponse:
    """列出安装包目录内容。动态生成，放入文件后刷新页面即可见。"""
    files = sorted(
        (p for p in _DOWNLOADS_DIR.iterdir() if p.is_file() and not p.name.startswith(".")),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    rows = []
    for path in files:
        stat = path.stat()
        name = html.escape(path.name)
        href = urllib.parse.quote(path.name)
        modified = time.strftime("%Y-%m-%d %H:%M", time.localtime(stat.st_mtime))
        rows.append(
            f'<a class="item" href="/downloads/files/{href}" download>'
            f'<span class="name">{name}</span>'
            f'<span class="meta">{_human_size(stat.st_size)} · {modified}</span></a>'
        )
    body = (
        "".join(rows)
        if rows
        else '<p class="empty">暂无安装包。请管理员把安装包放入 <code>DOWNLOADS_DIR</code>（默认 data/downloads）目录。</p>'
    )
    return HTMLResponse(
        "<!doctype html><html lang=\"zh\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<title>Nova Agent 桌面客户端下载</title><style>"
        "body{background:#101014;color:#e8e8ee;font:14px/1.6 system-ui,'Segoe UI',sans-serif;"
        "display:flex;justify-content:center;padding:48px 16px;margin:0}"
        ".wrap{width:100%;max-width:560px}h1{font-size:18px;margin:0 0 4px}"
        "p.sub{color:#9a9aa8;font-size:12.5px;margin:0 0 24px}"
        "a.item{display:flex;justify-content:space-between;gap:16px;padding:12px 14px;margin-bottom:8px;"
        "border:1px solid #26262e;border-radius:10px;text-decoration:none;color:#e8e8ee;font-size:13px}"
        "a.item:hover{border-color:#4c6fff}"
        ".name{font-weight:500;word-break:break-all}.meta{color:#9a9aa8;white-space:nowrap;font-size:11.5px}"
        ".empty{color:#9a9aa8;font-size:12.5px;border:1px dashed #26262e;border-radius:10px;padding:16px}"
        "code{background:#1a1a22;border-radius:4px;padding:1px 5px;font-size:11.5px}"
        "</style></head><body><div class=\"wrap\">"
        "<h1>Nova Agent 桌面客户端</h1>"
        "<p class=\"sub\">安装后输入本服务器地址即可使用，数据仍保存在服务器上。</p>"
        f"{body}"
        "</div></body></html>"
    )


app.mount("/downloads/files", StaticFiles(directory=_DOWNLOADS_DIR), name="downloads_files")

_FRONTEND_DIST = (
    Path(settings.frontend_dist)
    if settings.frontend_dist
    else Path(__file__).resolve().parents[2] / "frontend" / "dist"
)

if settings.app_env == "prod" and _FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=_FRONTEND_DIST, html=True), name="frontend")
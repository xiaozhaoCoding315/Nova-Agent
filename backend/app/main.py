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

VERSION = "2.1.0"
_CLEANUP_INTERVAL_S = 3600


async def _maintenance_once() -> dict:
    """One maintenance pass. Local mode deliberately keeps the list small."""
    from app.core.memory.cleanup import run_cleanup

    summary = await run_cleanup()
    if settings.is_local:
        from app.core.indexing.retry import retry_pending_indexes

        summary["index_retried"] = await retry_pending_indexes()
        return summary

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
        from app.core.debt.service import scan_stale_repos
        summary["debt_scanned"] = await scan_stale_repos()
    except Exception:
        logger.exception("debt_scan_failed")
    try:
        from app.core.reflection.service import extract_lessons
        summary["lessons_extracted"] = await extract_lessons()
    except Exception:
        logger.exception("reflection_failed")
    return summary


async def _cleanup_loop() -> None:
    """Hourly maintenance: long-term memory + mode-specific cleanup."""
    while True:
        try:
            summary = await _maintenance_once()
            logger.info("cleanup_done", **summary)
        except ImportError:
            pass
        except Exception:
            logger.exception("cleanup_failed")
        await asyncio.sleep(_CLEANUP_INTERVAL_S)


@asynccontextmanager
async def lifespan(_: FastAPI):
    setup_logging()
    if settings.is_local:
        from app.local.runtime import validate_local_settings

        validate_local_settings()
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
# 运维把安装包（如 Nova-Agent-Setup-2.1.0.exe）放进 DOWNLOADS_DIR 后，用户即可在
# 登录页点「下载桌面客户端」或直接访问 /downloads 获取；无需认证。
_DOWNLOADS_DIR = Path(settings.downloads_dir)
_DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)


def _human_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{size} B"
        size /= 1024
    return f"{size:.1f} GB"


def _platform_label(filename: str) -> str:
    lower = filename.lower()
    if lower.endswith(".exe") or "windows" in lower or "win-" in lower:
        return "Windows"
    if lower.endswith(".dmg") or "macos" in lower or "darwin" in lower:
        return "macOS"
    if lower.endswith((".appimage", ".deb", ".rpm", ".tar.gz")):
        return "Linux"
    return "安装包"


_DOWNLOADS_STYLE = """
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body {
  margin: 0; min-height: 100vh; background: #0B0C0E; color: #EDE8DE;
  font: 14px/1.6 -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
  "Microsoft YaHei", sans-serif;
  display: flex; justify-content: center; padding: 40px 20px 64px;
}
.wrap { width: 100%; max-width: 640px; }
.top { display: flex; align-items: center; gap: 10px; margin-bottom: 56px; }
.wordmark {
  display: flex; align-items: center; gap: 8px; font: 500 11px/1 ui-monospace,
  "SFMono-Regular", "JetBrains Mono", Consolas, monospace; letter-spacing: .18em;
  text-transform: uppercase; color: #9A958C;
}
.dot { width: 6px; height: 6px; border-radius: 50%; background: #8FE388; }
.top a {
  margin-left: auto; color: #9A958C; text-decoration: none; font-size: 12px;
  transition: color .15s ease;
}
.top a:hover { color: #EDE8DE; }
.eyebrow {
  font: 500 10px/1 ui-monospace, "SFMono-Regular", Consolas, monospace;
  letter-spacing: .2em; text-transform: uppercase; color: #6B675F; margin: 0 0 14px;
}
h1 { margin: 0 0 10px; font-size: 30px; line-height: 1.2; letter-spacing: -.02em; font-weight: 600; }
.sub { margin: 0 0 32px; color: #9A958C; font-size: 13px; max-width: 46em; }
.note {
  margin: 0 0 28px; padding: 10px 12px; border-left: 2px solid #2A2E34;
  color: #6B675F; font-size: 12px;
}
a.item {
  display: flex; align-items: center; justify-content: space-between; gap: 16px;
  padding: 14px 16px; margin-bottom: 8px; border: 1px solid #2A2E34; border-radius: 6px;
  background: #121417; text-decoration: none; color: #EDE8DE;
  transition: border-color .15s ease, background .15s ease;
}
a.item:hover { border-color: #8FE388; background: #1A1D21; }
.left { min-width: 0; display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }
.badge {
  font: 500 9px/1 ui-monospace, Consolas, monospace; letter-spacing: .12em;
  text-transform: uppercase; color: #8FE388; border: 1px solid #20351F;
  background: #20351F; border-radius: 3px; padding: 3px 5px; white-space: nowrap;
}
.name { font: 500 13px/1.4 ui-monospace, "SFMono-Regular", Consolas, monospace; word-break: break-all; }
.meta { color: #6B675F; white-space: nowrap; font: 11px/1 ui-monospace, Consolas, monospace; }
.empty {
  color: #9A958C; font-size: 13px; border: 1px dashed #2A2E34; border-radius: 6px; padding: 20px;
}
code {
  background: #1A1D21; border: 1px solid #2A2E34; border-radius: 3px;
  padding: 1px 5px; font: 11px ui-monospace, Consolas, monospace; color: #9A958C;
}
.foot {
  margin-top: 40px; padding-top: 16px; border-top: 1px solid #1A1D21;
  color: #6B675F; font-size: 12px; display: flex; gap: 16px; flex-wrap: wrap;
}
.foot a { color: #9A958C; text-decoration: underline; text-underline-offset: 3px; }
.foot a:hover { color: #8FE388; }
@media (max-width: 520px) {
  body { padding: 24px 16px 48px; }
  .top { margin-bottom: 36px; }
  h1 { font-size: 25px; }
  a.item { align-items: flex-start; flex-direction: column; gap: 8px; }
}
"""


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
        platform = html.escape(_platform_label(path.name))
        modified = time.strftime("%Y-%m-%d %H:%M", time.localtime(stat.st_mtime))
        rows.append(
            f'<a class="item" href="/downloads/files/{href}" download>'
            f'<span class="left"><span class="badge">{platform}</span>'
            f'<span class="name">{name}</span></span>'
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
        "<meta name=\"color-scheme\" content=\"dark\">"
        "<title>桌面客户端 · Nova Agent</title><style>"
        f"{_DOWNLOADS_STYLE}</style></head><body><div class=\"wrap\">"
        "<div class=\"top\"><span class=\"wordmark\"><span class=\"dot\"></span>Nova Agent</span>"
        "<a href=\"/\">返回工作台 →</a></div>"
        "<p class=\"eyebrow\">Desktop client</p>"
        "<h1>在桌面打开 Nova Agent</h1>"
        "<p class=\"sub\">安装包有两种用法：在本机运行（自带后端与数据库，数据留在你的电脑），"
        "或连接本服务器（仓库、会话与执行结果保存在服务器上）。</p>"
        "<p class=\"note\">也可以不安装任何东西，直接在浏览器里使用相同的工作台。"
        "安装包更新后重新下载覆盖安装即可，数据与会话不受影响。"
        "本机运行没有容器隔离，Agent 执行的命令会直接影响那台电脑。</p>"
        f"{body}"
        "<div class=\"foot\"><a href=\"/\">在浏览器中打开</a>"
        "<span>安装后选择「在本机运行」或填写本服务器地址。</span></div>"
        "</div></body></html>"
    )


app.mount("/downloads/files", StaticFiles(directory=_DOWNLOADS_DIR), name="downloads_files")

_FRONTEND_DIST = (
    Path(settings.frontend_dist)
    if settings.frontend_dist
    else Path(__file__).resolve().parents[2] / "frontend" / "dist"
)

if (settings.app_env == "prod" or settings.is_local) and _FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=_FRONTEND_DIST, html=True), name="frontend")
import asyncio
import time
from pathlib import Path

import structlog
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.api.v1.router import api_router
from app.core.logging_setup import setup_logging

logger = structlog.get_logger()

VERSION = "2.2.1"
_CLEANUP_INTERVAL_S = 3600


async def _maintenance_once() -> dict:
    """One maintenance pass. Local mode deliberately keeps the list small."""
    from app.core.memory.cleanup import run_cleanup

    summary = await run_cleanup()
    try:
        from app.core.turns.store import cleanup_old_turns

        summary["turns_pruned"] = await cleanup_old_turns()
    except Exception:
        logger.exception("turn_cleanup_failed")
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
    try:
        from app.core.turns.store import recover_interrupted_turns

        interrupted = await recover_interrupted_turns()
        if interrupted:
            logger.info("turns_marked_interrupted", count=interrupted)
    except Exception:
        logger.warning("turn_recovery_failed", exc_info=True)
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
# 运维把安装包（如 Nova-Agent-Setup-2.1.2.exe）放进 DOWNLOADS_DIR 后，用户即可在
# 登录页点「下载桌面客户端」或直接访问 /downloads 获取；无需认证。
_DOWNLOADS_DIR = Path(settings.downloads_dir)
_DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)


# 列表由前端 /downloads 路由渲染（数据来自 /api/v1/downloads），
# 这里只保留安装包直链。页面不再由后端内联 HTML 生成，避免两套设计语言。
app.mount("/downloads/files", StaticFiles(directory=_DOWNLOADS_DIR), name="downloads_files")

_FRONTEND_DIST = (
    Path(settings.frontend_dist)
    if settings.frontend_dist
    else Path(__file__).resolve().parents[2] / "frontend" / "dist"
)


@app.get("/{path:path}", include_in_schema=False, response_model=None)
async def frontend(path: str) -> FileResponse:
    """前端产物：有对应文件的直接返回，其余页面路径交给 SPA 自己渲染。

    之前这里是 `StaticFiles(html=True)` 挂在 `/` 上，匹配不到文件会直接 404，
    于是 `/downloads` 和未知路径都进不了 React，前端既没有下载页也画不出 404。
    现在由这条路由兜底：

    - `assets/*.js` 这类带扩展名的路径缺文件就返回真 404，不会被 HTML 外壳
      伪装成 200（否则浏览器会拿一个 index.html 去当模块解析）；
    - 其余无扩展名路径一律吐 index.html，由前端按 `location.pathname`
      决定渲染工作台、下载页还是 404。
    """
    if settings.app_env != "prod" and not settings.is_local:
        raise HTTPException(status_code=404, detail="not found")
    # 未知的 API 路径必须保持 JSON 404：客户端按状态码与 detail 处理错误，
    # 收到一张 HTML 页面只会把「接口不存在」显示成解析失败。
    if path == "api" or path.startswith("api/"):
        raise HTTPException(status_code=404, detail="not found")
    root = _FRONTEND_DIST.resolve()
    candidate = (root / path).resolve()
    if candidate.is_file() and root in candidate.parents:
        return FileResponse(candidate)
    if "." in path.rsplit("/", 1)[-1]:
        raise HTTPException(status_code=404, detail="not found")
    index = root / "index.html"
    if not index.is_file():
        raise HTTPException(status_code=404, detail="前端产物不存在")
    return FileResponse(index, media_type="text/html")
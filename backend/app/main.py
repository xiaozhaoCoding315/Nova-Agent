import asyncio
import time
from pathlib import Path

import structlog
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
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

_FRONTEND_DIST = (
    Path(settings.frontend_dist)
    if settings.frontend_dist
    else Path(__file__).resolve().parents[2] / "frontend" / "dist"
)

if settings.app_env == "prod" and _FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=_FRONTEND_DIST, html=True), name="frontend")
import asyncio
import time

import structlog
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.api.v1.router import api_router
from app.core.logging_setup import setup_logging

logger = structlog.get_logger()

_CLEANUP_INTERVAL_S = 3600  # 每小时


async def _cleanup_loop() -> None:
    while True:
        try:
            from app.core.memory.store import run_ttl_cleanup, run_session_cleanup
            await run_session_cleanup()
            await run_ttl_cleanup()
            logger.info("cleanup_done")
        except Exception:
            logger.exception("cleanup_failed")
        await asyncio.sleep(_CLEANUP_INTERVAL_S)


@asynccontextmanager
async def lifespan(_: FastAPI):
    setup_logging()
    logger.info("NovaTech starting", version="0.1.0")
    task = asyncio.create_task(_cleanup_loop())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    logger.info("NovaTech shutting down")


app = FastAPI(title="NovaTech Agent", version="0.1.0", lifespan=lifespan)


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

from fastapi.staticfiles import StaticFiles
from pathlib import Path

_FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"

if settings.app_env == "prod" and _FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=_FRONTEND_DIST, html=True), name="frontend")

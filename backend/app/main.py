import asyncio
import structlog
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.api.v1.router import api_router

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

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")

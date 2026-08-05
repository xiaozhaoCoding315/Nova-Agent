import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.api.v1.router import api_router

logger = structlog.get_logger()

app = FastAPI(title="NovaTech Agent", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")


@app.on_event("startup")
async def on_startup():
    logger.info("NovaTech starting", version="0.1.0")


@app.on_event("shutdown")
async def on_shutdown():
    logger.info("NovaTech shutting down")

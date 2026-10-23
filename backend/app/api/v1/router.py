from fastapi import APIRouter

from app.api.v1 import (
    admin, auth, builder, changes, chat, contracts, deploys, git_ops, jobs, memory, repos,
    settings_llm, status, tasks,
)

api_router = APIRouter()
api_router.include_router(admin.router, tags=["admin"])
api_router.include_router(auth.router, tags=["auth"])
api_router.include_router(builder.router, tags=["builder"])
api_router.include_router(changes.router, tags=["changes"])
api_router.include_router(chat.router, tags=["chat"])
api_router.include_router(contracts.router, tags=["contracts"])
api_router.include_router(deploys.router, tags=["deploys"])
api_router.include_router(git_ops.router, tags=["git"])
api_router.include_router(jobs.router, tags=["jobs"])
api_router.include_router(memory.router, tags=["memory"])
api_router.include_router(repos.router, tags=["repos"])
api_router.include_router(settings_llm.router, tags=["settings"])
api_router.include_router(tasks.router, tags=["tasks"])
api_router.include_router(status.router, tags=["status"])
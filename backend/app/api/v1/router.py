from fastapi import APIRouter

from app.api.v1 import auth, builder, chat, git_ops, repos, status, tasks

api_router = APIRouter()
api_router.include_router(auth.router, tags=["auth"])
api_router.include_router(chat.router, tags=["chat"])
api_router.include_router(builder.router, tags=["builder"])
api_router.include_router(git_ops.router, tags=["git"])
api_router.include_router(repos.router, tags=["repos"])
api_router.include_router(tasks.router, tags=["tasks"])
api_router.include_router(status.router, tags=["status"])
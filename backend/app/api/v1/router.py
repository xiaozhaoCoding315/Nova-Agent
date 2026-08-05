from fastapi import APIRouter
from app.api.v1 import health, chat, knowledge, memory, graph, evaluation, dataset, harness, sandbox, security, tasks

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(chat.router, tags=["chat"])
api_router.include_router(knowledge.router, tags=["knowledge"])
api_router.include_router(memory.router, tags=["memory"])
api_router.include_router(graph.router, tags=["graph"])
api_router.include_router(evaluation.router, tags=["evaluation"])
api_router.include_router(dataset.router, tags=["dataset"])
api_router.include_router(harness.router, tags=["harness"])
api_router.include_router(sandbox.router, tags=["sandbox"])
api_router.include_router(security.router, tags=["security"])
api_router.include_router(tasks.router, tags=["tasks"])

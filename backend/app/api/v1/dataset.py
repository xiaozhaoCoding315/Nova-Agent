from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional
from app.core.evaluation.dataset import (
    add_golden_query, list_queries, get_query, delete_query,
    seed_sample_queries, get_dataset_stats,
)

router = APIRouter()


class GoldenQueryCreate(BaseModel):
    query: str
    category: str = "general"
    relevant_ids: list = []
    notes: str = ""


@router.get("/dataset/queries")
async def api_list_queries(category: Optional[str] = None):
    return await list_queries(category)


@router.post("/dataset/queries")
async def api_add_query(q: GoldenQueryCreate):
    qid = await add_golden_query(q.query, q.category, q.relevant_ids, q.notes)
    return {"id": qid, "query": q.query}


@router.get("/dataset/queries/{query_id}")
async def api_get_query(query_id: int):
    return await get_query(query_id)


@router.delete("/dataset/queries/{query_id}")
async def api_delete_query(query_id: int):
    await delete_query(query_id)
    return {"deleted": query_id}


@router.post("/dataset/seed")
async def api_seed():
    count = await seed_sample_queries()
    return {"seeded": count}


@router.get("/dataset/stats")
async def api_stats():
    return await get_dataset_stats()

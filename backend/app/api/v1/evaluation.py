import json
import time
import asyncio
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional
from app.core.evaluation.runner import evaluate_single_query, run_evaluation_suite
from app.core.evaluation.reporter import generate_report
from app.core.evaluation.dataset import list_eval_results

router = APIRouter()


class EvalQuery(BaseModel):
    query: str
    relevant_ids: Optional[list] = None


class EvalRequest(BaseModel):
    queries: list[EvalQuery]
    mode: str = "all"


@router.post("/eval/single")
async def eval_single(query: EvalQuery):
    return await evaluate_single_query(query.query, query.relevant_ids, mode="all")


@router.post("/eval/suite")
async def eval_suite(req: EvalRequest):
    queries = [{"query": q.query, "relevant_ids": q.relevant_ids} for q in req.queries]
    return await run_evaluation_suite(queries, mode=req.mode)


@router.get("/eval/report/{run_name}")
async def eval_report(run_name: str):
    report = await generate_report(run_name)
    return {"report": report}


@router.get("/eval/results")
async def eval_results(run_name: str = None):
    return await list_eval_results(run_name)

"""Evaluation runner: run full evaluation on a test set and persist results."""
import asyncio
import time
import uuid
from app.core.rag.retriever import retrieve
from app.core.evaluation.metrics import evaluate_retrieval
from app.core.evaluation.ragas import evaluate_generation
from app.core.evaluation.dataset import save_eval_result, list_eval_results, get_eval_run_summary
from app.core.llm.factory import get_llm


async def evaluate_single_query(
    query: str,
    relevant_ids: list = None,
    golden_answer: str = "",
    mode: str = "all",  # "retrieval" | "generation" | "all"
    query_id: int = None,
    run_name: str = None,
) -> dict:
    """Evaluate a single query end-to-end.

    Optionally persists the result to the database when *run_name* is provided.
    """
    result: dict = {"query": query, "query_id": query_id}

    # --- Retrieval phase ---
    t0 = time.perf_counter()
    chunks = []
    try:
        chunks = await retrieve(query, top_k=10)
    except Exception as e:
        result["retrieval_error"] = str(e)

    retrieval_ms = (time.perf_counter() - t0) * 1000
    result["retrieval_time_ms"] = round(retrieval_ms, 1)
    result["retrieved_count"] = len(chunks)

    # Retrieval metrics (if ground truth provided)
    if relevant_ids and mode in ("retrieval", "all"):
        retrieved_ids = [c.id for c in chunks]
        result["retrieval_metrics"] = evaluate_retrieval(retrieved_ids, relevant_ids)

    # --- Generation phase ---
    answer = ""
    ragas: dict = {}
    if mode in ("generation", "all") and chunks:
        context = "\n---\n".join(c.content for c in chunks)
        messages = [
            {"role": "system", "content": f"你是NovaTech技术助手。基于以下上下文回答：\n\n{context}"},
            {"role": "user", "content": query},
        ]
        try:
            llm = get_llm()
            async for token in llm.astream(messages):
                answer += token
        except Exception as e:
            answer = f"[生成错误: {e}]"

        result["answer"] = answer

        # RAGAS evaluation
        if mode == "all":
            ragas = await evaluate_generation(query, answer, context)
            result["ragas_scores"] = ragas

        # Compare answer to golden answer (simple token-overlap score)
        if golden_answer:
            result["golden_answer"] = golden_answer
            result["answer_similarity"] = _answer_similarity(answer, golden_answer)

    duration_ms = (time.perf_counter() - t0) * 1000
    result["duration_ms"] = round(duration_ms, 1)

    # --- Persist ---
    if run_name and query_id is not None:
        await save_eval_result(
            run_name=run_name,
            eval_type=mode,
            query_id=query_id,
            query_text=query,
            metrics=result.get("retrieval_metrics", {}),
            ragas_scores=ragas,
            answer=answer,
            duration_ms=duration_ms,
        )

    return result


# ---------------------------------------------------------------------------
# Suite runner + report generation
# ---------------------------------------------------------------------------

async def run_evaluation_suite(queries: list, mode: str = "all",
                               run_name: str = None) -> dict:
    """Run evaluation on multiple queries.

    *queries*      — list of dicts with keys ``query``, ``relevant_ids``, ``id``,
                     ``golden_answer`` (last two optional).
    *run_name*     — when given, results are persisted and an aggregate
                     report is generated under ``report``.
    """
    results = []
    for q in queries:
        r = await evaluate_single_query(
            query=q.get("query", "") if isinstance(q, dict) else str(q),
            relevant_ids=q.get("relevant_ids") if isinstance(q, dict) else None,
            golden_answer=q.get("golden_answer", "") if isinstance(q, dict) else "",
            mode=mode,
            query_id=q.get("id") if isinstance(q, dict) else None,
            run_name=run_name,
        )
        results.append(r)

    return _build_summary(results, run_name, mode)


def _build_summary(results: list, run_name: str | None, mode: str) -> dict:
    """Aggregate a suite result list into a report dict."""
    summary: dict = {
        "run_name": run_name or f"run-{uuid.uuid4().hex[:8]}",
        "eval_type": mode,
        "total_queries": len(results),
        "results": results,
    }

    # Retrieval time
    retrieval_times = [r["retrieval_time_ms"] for r in results if "retrieval_time_ms" in r]
    if retrieval_times:
        summary["avg_retrieval_time_ms"] = round(sum(retrieval_times) / len(retrieval_times), 1)

    total_durations = [r["duration_ms"] for r in results if "duration_ms" in r]
    if total_durations:
        summary["avg_total_time_ms"] = round(sum(total_durations) / len(total_durations), 1)

    # Average RAGAS scores
    ragas_keys = ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]
    for key in ragas_keys:
        scores = [r["ragas_scores"][key] for r in results
                  if "ragas_scores" in r and key in r["ragas_scores"]]
        if scores:
            summary[f"avg_{key}"] = round(sum(scores) / len(scores), 4)

    # Average retrieval metrics
    retrieval_metric_keys = ["recall@1", "recall@3", "recall@5", "recall@10",
                             "ndcg@1", "ndcg@3", "ndcg@5", "ndcg@10",
                             "hit_rate@1", "hit_rate@3", "hit_rate@5", "hit_rate@10",
                             "mrr"]
    for key in retrieval_metric_keys:
        vals = [r["retrieval_metrics"][key] for r in results
                if "retrieval_metrics" in r and key in r["retrieval_metrics"]]
        if vals:
            summary[f"avg_{key}"] = round(sum(vals) / len(vals), 4)

    # Answer similarity (golden answer comparison)
    sims = [r["answer_similarity"] for r in results if "answer_similarity" in r]
    if sims:
        summary["avg_answer_similarity"] = round(sum(sims) / len(sims), 4)

    # Errors / missing
    summary["errors"] = [r for r in results if "retrieval_error" in r]
    summary["error_count"] = len(summary["errors"])

    return summary


def _answer_similarity(answer: str, golden: str) -> float:
    """Token-overlap similarity between answer and golden answer (0-1)."""
    if not answer or not golden:
        return 0.0
    a_tokens = set(_tokenize(answer))
    g_tokens = set(_tokenize(golden))
    if not g_tokens:
        return 0.0
    overlap = a_tokens & g_tokens
    return round(len(overlap) / len(g_tokens), 4)


def _tokenize(text: str) -> list[str]:
    """Simple tokenization: whitespace + punctuation split, lowercase."""
    import re
    return re.findall(r"[\w一-鿿]+", text.lower())


# ---------------------------------------------------------------------------
# Report export
# ---------------------------------------------------------------------------

async def generate_report(run_name: str) -> dict:
    """Build a full report for a persisted evaluation run."""
    summary = await get_eval_run_summary(run_name)
    detail_rows = await list_eval_results(run_name=run_name, limit=500)

    return {
        "report_version": "1.0",
        "run_name": run_name,
        "summary": summary,
        "results": detail_rows,
    }

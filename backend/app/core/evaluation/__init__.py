from app.core.evaluation.metrics import evaluate_retrieval, recall_at_k, mrr, ndcg_at_k, hit_rate
from app.core.evaluation.ragas import evaluate_generation
from app.core.evaluation.runner import evaluate_single_query, run_evaluation_suite
from app.core.evaluation.dataset import (
    add_golden_query, list_queries, get_query, delete_query,
    seed_sample_queries, get_dataset_stats, save_eval_result, list_eval_results
)
from app.core.evaluation.reporter import generate_report

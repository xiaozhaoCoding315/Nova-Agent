"""The offline memory golden set guards recall, scope leaks and staleness."""
from evals import memory_eval


def test_memory_golden_set_meets_targets():
    metrics = memory_eval.run()

    assert metrics["passed"] is True
    assert metrics["recall_at_8"] >= metrics["baseline_recall_at_8"]
    assert metrics["scope_leak"] == 0
    assert metrics["stale_rate"] <= 0.05
    assert metrics["duplicate_rate"] <= 0.02
    assert metrics["compaction_retention"] >= 0.9
    assert metrics["memory_token_share"] <= 0.15


def test_memory_eval_check_mode_exits_zero():
    assert memory_eval.main(["--check"]) == 0


def test_ranked_facts_respect_scope_before_ranking():
    golden = memory_eval._load(memory_eval.GOLDEN_PATH)
    case = next(
        item for item in golden["cases"] if item["id"] == "thesis_context"
    )
    readable = memory_eval._readable(case["readable_scopes"])
    rows = memory_eval._active_rows(golden["facts"], readable)
    ranked = memory_eval.facts_mod.rank_fact_rows(
        case["query_embedding"], rows, golden["top_k"],
    )

    ids = [item[0] for item in ranked]
    assert {8, 9}.issubset(set(ids))
    assert 5 not in ids and 7 not in ids

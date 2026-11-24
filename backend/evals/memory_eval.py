"""Offline memory evaluation: recall, scope leaks, staleness and compaction.

The golden set is small and deterministic so it can run in CI without a
database, embeddings or an LLM.  ``rank_fact_rows`` is the same helper the
production fact retriever uses.
"""
import argparse
import json
from datetime import date
from pathlib import Path

from app.core.agent.context_meter import estimate_tokens
from app.core.memory import facts as facts_mod

HERE = Path(__file__).resolve().parent
GOLDEN_PATH = HERE / "memory_golden.json"
BASELINE_PATH = HERE / "memory_baseline.json"

TARGETS = {
    "scope_leak": 0,
    "stale_rate": 0.05,
    "duplicate_rate": 0.02,
    "compaction_retention": 0.90,
    "memory_token_share": 0.15,
}


def _scope_key(scope_type: str, scope_id: str) -> tuple[str, str]:
    return (scope_type or "global", scope_id or "")


def _readable(scopes: list[list[str]]) -> set[tuple[str, str]]:
    return {_scope_key(item[0], item[1] if len(item) > 1 else "") for item in scopes}


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _active_rows(facts: list[dict], readable: set[tuple[str, str]]) -> list[tuple]:
    return [
        (
            fact["id"], fact["content"], fact.get("embedding"),
            fact.get("importance", 1.0),
        )
        for fact in facts
        if fact.get("status", "active") == "active"
        and _scope_key(fact["scope_type"], fact.get("scope_id", "")) in readable
    ]


def _scope_by_id(facts: list[dict]) -> dict[int, tuple[str, str]]:
    return {
        fact["id"]: _scope_key(fact["scope_type"], fact.get("scope_id", ""))
        for fact in facts
    }


def _duplicate_rate(facts: list[dict]) -> float:
    active = [
        fact for fact in facts
        if fact.get("status", "active") == "active" and fact.get("embedding")
    ]
    total_pairs = 0
    duplicates = 0
    for index, left in enumerate(active):
        for right in active[index + 1:]:
            total_pairs += 1
            if _scope_key(left["scope_type"], left.get("scope_id", "")) != _scope_key(
                right["scope_type"], right.get("scope_id", "")
            ):
                continue
            if _cosine(left["embedding"], right["embedding"]) >= facts_mod.DEDUP_COSINE_THRESHOLD:
                duplicates += 1
    return duplicates / total_pairs if total_pairs else 0.0


def _compaction_retention(golden: dict) -> float:
    block = golden.get("compaction") or {}
    keywords = block.get("required_keywords") or []
    summary = str(block.get("summary") or "")
    if not keywords:
        return 1.0
    present = sum(1 for keyword in keywords if keyword in summary)
    return present / len(keywords)


def evaluate(golden: dict, baseline: dict | None = None) -> dict:
    top_k = int(golden.get("top_k") or 8)
    facts = golden.get("facts") or []
    scope_by_id = _scope_by_id(facts)
    selected_ids: list[int] = []
    leaked = 0
    stale = 0
    recalls: list[float] = []
    token_share_samples: list[float] = []
    context_window = int(golden.get("context_window") or 8000)

    for case in golden.get("cases") or []:
        readable = _readable(case.get("readable_scopes") or [])
        rows = _active_rows(facts, readable)
        ranked = facts_mod.rank_fact_rows(
            case.get("query_embedding"), rows, top_k,
        )
        ids = [item[0] for item in ranked]
        selected_ids.extend(ids)
        must_recall = [int(fact_id) for fact_id in case.get("must_recall") or []]
        if must_recall:
            recalls.append(
                sum(1 for fact_id in must_recall if fact_id in ids) / len(must_recall)
            )
        forbidden = {int(fact_id) for fact_id in case.get("forbidden") or []}
        for fact_id in ids:
            if fact_id in forbidden:
                leaked += 1
            scope = scope_by_id.get(fact_id)
            if scope is not None and scope not in readable:
                leaked += 1
        stale += sum(
            1 for fact_id in ids
            if next(
                (f for f in facts if f["id"] == fact_id), {}
            ).get("status", "active") != "active"
        )
        memory_tokens = sum(
            estimate_tokens(content) for _, content, _ in ranked
        )
        token_share_samples.append(memory_tokens / max(1, context_window))

    recall_at_8 = sum(recalls) / len(recalls) if recalls else 1.0
    stale_rate = stale / len(selected_ids) if selected_ids else 0.0
    duplicate_rate = _duplicate_rate(facts)
    compaction_retention = _compaction_retention(golden)
    memory_token_share = max(token_share_samples) if token_share_samples else 0.0
    baseline_recall = float((baseline or {}).get("recall_at_8", 0.0))

    checks = {
        "recall_at_8": recall_at_8 + 1e-9 >= baseline_recall,
        "scope_leak": leaked <= TARGETS["scope_leak"],
        "stale_rate": stale_rate <= TARGETS["stale_rate"],
        "duplicate_rate": duplicate_rate <= TARGETS["duplicate_rate"],
        "compaction_retention": compaction_retention >= TARGETS["compaction_retention"],
        "memory_token_share": memory_token_share <= TARGETS["memory_token_share"],
    }
    return {
        "recall_at_8": round(recall_at_8, 4),
        "baseline_recall_at_8": round(baseline_recall, 4),
        "scope_leak": leaked,
        "stale_rate": round(stale_rate, 4),
        "duplicate_rate": round(duplicate_rate, 4),
        "compaction_retention": round(compaction_retention, 4),
        "memory_token_share": round(memory_token_share, 4),
        "cases": len(golden.get("cases") or []),
        "checks": checks,
        "passed": all(checks.values()),
    }


def run() -> dict:
    baseline = _load(BASELINE_PATH) if BASELINE_PATH.exists() else None
    return evaluate(_load(GOLDEN_PATH), baseline)


def _print_report(metrics: dict) -> None:
    print(f"Memory eval · {date.today().isoformat()}")
    for key in (
        "recall_at_8", "scope_leak", "stale_rate", "duplicate_rate",
        "compaction_retention", "memory_token_share",
    ):
        mark = "PASS" if metrics["checks"][key] else "FAIL"
        print(f"  {mark:4}  {key}: {metrics[key]}")
    print(f"  {'PASS' if metrics['passed'] else 'FAIL'}  overall")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the offline memory eval")
    parser.add_argument("--json", type=Path, help="write metrics JSON here")
    parser.add_argument("--write-baseline", action="store_true")
    parser.add_argument("--check", action="store_true", help="exit 1 when off target")
    args = parser.parse_args(argv)

    metrics = run()
    _print_report(metrics)
    if args.json:
        args.json.write_text(
            json.dumps(metrics, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if args.write_baseline:
        BASELINE_PATH.write_text(
            json.dumps(metrics, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return 1 if args.check and not metrics["passed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

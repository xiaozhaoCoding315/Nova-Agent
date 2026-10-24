"""Debt radar: deterministic per-repo technical-debt metrics + weekly trend.

Everything is computed from the existing index tables (repo_files / chunks /
symbols) — no LLM, no judgment, fully reproducible.  The score is a weighted
blend of structural signals so week-over-week deltas mean something.
"""
import json

import structlog

from app.db import execute, query

logger = structlog.get_logger()

LONG_FUNCTION_LINES = 80
HUGE_FILE_LINES = 800
MAX_SNAPSHOTS_KEPT = 30

# Weights must sum to 100.
_WEIGHTS = {"long_functions": 40, "todos": 25, "test_gap": 25, "huge_files": 10}


async def compute_metrics(repo_id: str) -> dict:
    files = await query(
        "SELECT COUNT(*), COALESCE(SUM(line_count), 0) FROM repo_files WHERE repo_id = %s",
        (repo_id,),
    )
    file_count = int(files[0][0]) if files else 0

    todos = await query(
        "SELECT COUNT(*) FROM chunks WHERE repo_id = %s "
        "AND (content ILIKE '%%TODO%%' OR content ILIKE '%%FIXME%%' OR content ILIKE '%%HACK%%')",
        (repo_id,),
    )
    todo_chunks = int(todos[0][0]) if todos else 0

    long_funcs = await query(
        "SELECT name, kind, (line_end - line_start) AS span FROM symbols "
        "WHERE repo_id = %s AND kind IN ('function', 'method', 'func', 'method_declaration', 'function_declaration') "
        "AND line_end IS NOT NULL AND line_start IS NOT NULL "
        "AND (line_end - line_start) > %s ORDER BY span DESC LIMIT 5",
        (repo_id, LONG_FUNCTION_LINES),
    )
    long_func_count = await query(
        "SELECT COUNT(*) FROM symbols "
        "WHERE repo_id = %s AND kind IN ('function', 'method', 'func', 'method_declaration', 'function_declaration') "
        "AND line_end IS NOT NULL AND line_start IS NOT NULL "
        "AND (line_end - line_start) > %s",
        (repo_id, LONG_FUNCTION_LINES),
    )
    long_func_total = int(long_func_count[0][0]) if long_func_count else 0

    symbol_total = await query(
        "SELECT COUNT(*) FROM symbols WHERE repo_id = %s "
        "AND kind IN ('function', 'method', 'func', 'method_declaration', 'function_declaration')",
        (repo_id,),
    )
    symbol_count = int(symbol_total[0][0]) if symbol_total else 0

    test_files = await query(
        "SELECT COUNT(*) FROM repo_files WHERE repo_id = %s "
        "AND (path ILIKE 'tests/%%' OR path ILIKE 'test/%%' OR path ILIKE '%%/tests/%%' "
        "OR path ILIKE '%%/test/%%' OR path ILIKE 'test_%%' OR path ILIKE '%%_test%%')",
        (repo_id,),
    )
    test_file_count = int(test_files[0][0]) if test_files else 0

    huge = await query(
        "SELECT path, line_count FROM repo_files WHERE repo_id = %s "
        "AND line_count > %s ORDER BY line_count DESC LIMIT 5",
        (repo_id, HUGE_FILE_LINES),
    )

    source_files = max(file_count - test_file_count, 1)
    test_ratio = min(1.0, test_file_count / file_count) if file_count else 0.0
    long_ratio = min(1.0, long_func_total / symbol_count) if symbol_count else 0.0
    todo_density = min(1.0, todo_chunks / max(source_files, 1) / 0.2)  # 1 todo per 5 files maxes it
    huge_ratio = min(1.0, len(huge) / 5.0) if file_count >= 10 else 0.0

    score = round(
        _WEIGHTS["long_functions"] * long_ratio
        + _WEIGHTS["todos"] * todo_density
        + _WEIGHTS["test_gap"] * (1.0 - test_ratio) * (0.5 if file_count < 5 else 1.0)
        + _WEIGHTS["huge_files"] * huge_ratio
    )
    return {
        "file_count": file_count,
        "test_file_count": test_file_count,
        "test_ratio": round(test_ratio, 3),
        "symbol_count": symbol_count,
        "long_function_count": long_func_total,
        "long_functions": [
            {"name": r[0], "kind": r[1], "lines": int(r[2] or 0)} for r in long_funcs
        ],
        "todo_chunk_count": todo_chunks,
        "huge_files": [{"path": r[0], "lines": int(r[1] or 0)} for r in huge],
        "score": max(0, min(100, score)),
    }


async def scan_repo(repo_id: str, user_id: int | None = None) -> dict:
    if user_id is None:
        rows = await query("SELECT user_id FROM repos WHERE id = %s", (repo_id,))
        if not rows:
            raise ValueError("仓库不存在")
        user_id = rows[0][0]
    metrics = await compute_metrics(repo_id)
    await execute(
        "INSERT INTO debt_snapshots (repo_id, user_id, score, metrics) VALUES (%s, %s, %s, %s)",
        (repo_id, user_id, metrics["score"],
         json.dumps(metrics, ensure_ascii=False, default=str)),
    )
    await execute(
        """
        DELETE FROM debt_snapshots WHERE repo_id = %s AND id NOT IN (
            SELECT id FROM debt_snapshots WHERE repo_id = %s
            ORDER BY created_at DESC LIMIT %s
        )
        """,
        (repo_id, repo_id, MAX_SNAPSHOTS_KEPT),
    )
    return metrics


async def get_report(repo_id: str, history: int = 8) -> dict:
    rows = await query(
        "SELECT score, metrics, created_at FROM debt_snapshots "
        "WHERE repo_id = %s ORDER BY created_at DESC LIMIT %s",
        (repo_id, history),
    )
    snapshots = [
        {"score": int(r[0]), "metrics": r[1] or {}, "created_at": r[2]}
        for r in reversed(rows)
    ]
    return {
        "latest": snapshots[-1] if snapshots else None,
        "history": snapshots,
    }


async def scan_stale_repos(max_repos: int = 3, stale_days: int = 7) -> int:
    """Weekly auto-scan hook for the maintenance loop."""
    rows = await query(
        """
        SELECT r.id FROM repos r
        WHERE r.status = 'ready' AND COALESCE(
            (SELECT MAX(s.created_at) FROM debt_snapshots s WHERE s.repo_id = r.id),
            '1970-01-01'::timestamptz
        ) < now() - (%s * interval '1 day')
        ORDER BY r.created_at DESC LIMIT %s
        """,
        (stale_days, max_repos),
    )
    scanned = 0
    for (repo_id,) in rows:
        try:
            await scan_repo(str(repo_id))
            scanned += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("debt_scan_failed", repo=str(repo_id), error=str(exc))
    return scanned

"""Change-impact analysis over the repo dependency graph."""
import re

from app.db import query

_IDENT = re.compile(r"^[A-Za-z_][\w.]*$")
_TEST_HINTS = ("/tests/", "/test/", "test_", "_test.", ".spec.", ".test.")


def _is_test(path: str) -> bool:
    lower = path.lower()
    return any(h in lower for h in _TEST_HINTS)


async def _find_symbols(repo_id: str, name: str) -> list[dict]:
    rows = await query(
        """
        SELECT s.name, s.kind, f.path, s.line_start, s.line_end, COALESCE(s.signature, '')
        FROM symbols s JOIN repo_files f ON f.id = s.file_id
        WHERE s.repo_id = %s AND s.name ILIKE %s
        ORDER BY (lower(s.name) = lower(%s)) DESC, (s.name ILIKE %s) DESC, length(s.name)
        LIMIT 5
        """,
        (repo_id, f"%{name}%", name, f"{name}%"),
    )
    return [
        {"name": r[0], "kind": r[1], "path": r[2],
         "line_start": r[3], "line_end": r[4], "signature": r[5]}
        for r in rows
    ]


async def _references(repo_id: str, symbol: str, limit: int = 12) -> list[dict]:
    if not _IDENT.match(symbol):
        return []
    pattern = r"\m" + symbol + r"\M"
    rows = await query(
        """
        SELECT f.path, MIN(c.line_start), COUNT(*)
        FROM chunks c JOIN repo_files f ON f.id = c.file_id
        WHERE c.repo_id = %s AND c.content ~ %s
        GROUP BY f.path ORDER BY COUNT(*) DESC LIMIT %s
        """,
        (repo_id, pattern, limit),
    )
    return [{"path": r[0], "line_start": r[1] or 0, "occurrences": int(r[2])} for r in rows]


def _dependents(
    targets: set[str], deps: list[dict], depth: int
) -> tuple[list[str], list[str], dict[str, int]]:
    reverse: dict[str, set[str]] = {}
    for dep in deps:
        reverse.setdefault(dep["resolved_path"], set()).add(dep["source_path"])

    direct: set[str] = set()
    for target in targets:
        direct |= reverse.get(target, set())
    direct -= targets

    all_deps = set(direct)
    levels = {p: 1 for p in direct}
    frontier = set(direct)
    for level in range(2, depth + 1):
        nxt: set[str] = set()
        for path in frontier:
            nxt |= reverse.get(path, set())
        nxt -= all_deps
        nxt -= targets
        for path in nxt:
            levels[path] = level
        all_deps |= nxt
        frontier = nxt
        if not frontier:
            break
    return sorted(direct), sorted(all_deps - direct), levels


async def analyze_impact(repo_id: str, raw_query: str, depth: int = 2) -> dict:
    """Return dependents, references, related tests and a risk assessment for
    a symbol name or file path inside one repo."""
    query_text = (raw_query or "").strip()
    if not query_text:
        return {"found": False, "risk": {"level": "unknown", "reasons": ["查询为空"]}}

    symbols = await _find_symbols(repo_id, query_text)
    exact = [s for s in symbols if s["name"].lower() == query_text.lower()]
    if exact:
        symbols = exact  # avoid substring matches polluting the target set
    targets = {s["path"] for s in symbols}

    if "/" in query_text or query_text.endswith((".py", ".ts", ".js", ".java", ".go", ".tsx", ".jsx")):
        rows = await query(
            "SELECT path FROM repo_files WHERE repo_id = %s AND path LIKE %s LIMIT 3",
            (repo_id, f"%{query_text}"),
        )
        targets |= {r[0] for r in rows}

    if not targets:
        return {
            "found": False,
            "query": query_text,
            "risk": {"level": "unknown", "reasons": ["未找到匹配的符号或文件"]},
        }

    ref_names = {s["name"] for s in symbols}
    if _IDENT.match(query_text):
        ref_names.add(query_text)
    refs: dict[str, dict] = {}
    for name in ref_names:
        for hit in await _references(repo_id, name):
            entry = refs.setdefault(hit["path"], {"path": hit["path"], "occurrences": 0,
                                                  "line_start": hit["line_start"]})
            entry["occurrences"] += hit["occurrences"]
            entry["line_start"] = min(entry["line_start"], hit["line_start"])
    references = sorted(refs.values(), key=lambda r: r["occurrences"], reverse=True)

    dep_rows = await query(
        "SELECT source_path, resolved_path FROM file_deps "
        "WHERE repo_id = %s AND resolved_path IS NOT NULL",
        (repo_id,),
    )
    direct, transitive, levels = _dependents(
        targets, [{"source_path": r[0], "resolved_path": r[1]} for r in dep_rows], depth
    )

    test_candidates = {
        p for p in [*targets, *direct, *transitive, *refs.keys()] if _is_test(p)
    }
    tests = sorted(test_candidates)

    risk_score = 0
    reasons: list[str] = []
    if direct:
        risk_score += min(len(direct), 5)
        reasons.append(f"{len(direct)} 个文件直接依赖目标")
    if transitive:
        risk_score += min(len(transitive), 3)
        reasons.append(f"另有 {len(transitive)} 个文件在 {depth} 层内间接依赖")
    if any(s["kind"] in ("class", "interface", "struct", "enum") for s in symbols):
        risk_score += 2
        reasons.append("目标是类型/类，变更通常波及更广")
    if not tests:
        risk_score += 2
        reasons.append("未发现相关测试，回归风险无法被测试覆盖")
    elif any(_is_test(p) for p in targets):
        reasons.append("目标本身是测试文件，影响面通常有限")
    level = "high" if risk_score >= 6 else "medium" if risk_score >= 3 else "low"

    command = ""
    if tests:
        command = "python -m pytest -q " + " ".join(tests[:8])

    return {
        "found": True,
        "query": query_text,
        "symbols": symbols,
        "targets": sorted(targets),
        "direct_dependents": direct,
        "transitive_dependents": transitive,
        "dependency_levels": levels,
        "references": references[:12],
        "tests": tests[:12],
        "risk": {"level": level, "score": risk_score, "reasons": reasons},
        "suggested_command": command,
        "note": "基于导入关系与符号引用的静态分析，不等价于完整编译器级影响分析。",
    }
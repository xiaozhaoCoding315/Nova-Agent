"""Deterministic repo brain: entry points, hot files, reading order,
module map, dependency graph and glossary. No LLM calls — reproducible."""
import posixpath
from collections import Counter, defaultdict

ENTRY_NAMES = {
    "main.py", "app.py", "manage.py", "run.py", "server.py", "wsgi.py", "asgi.py",
    "index.js", "server.js", "app.js", "index.ts", "main.ts", "main.go",
    "Main.java", "Application.java", "Program.cs", "index.tsx",
}
TEST_PATTERN_HINTS = ("/tests/", "/test/", "test_", "_test.", ".spec.", ".test.")

MAX_GRAPH_NODES = 24
MAX_GLOSSARY = 20


def _is_test(path: str) -> bool:
    lower = path.lower()
    return any(h in lower for h in TEST_PATTERN_HINTS)


def _module_of(path: str) -> str:
    parts = path.split("/")
    return parts[0] if len(parts) > 1 else "."


def build_brain(
    files: list[dict],
    symbols: list[dict],
    deps: list[dict],
    languages: dict[str, int],
) -> dict:
    """files: [{path, language, line_count, is_doc}]
    symbols: [{name, kind, path, line_start, signature}]
    deps: [{source_path, resolved_path}] (resolved only)"""
    paths = [f["path"] for f in files]
    inbound: Counter[str] = Counter()
    outbound: Counter[str] = Counter()
    edges: list[tuple[str, str]] = []
    for dep in deps:
        target = dep.get("resolved_path")
        source = dep.get("source_path")
        if not target or not source or target == source:
            continue
        edges.append((source, target))
        inbound[target] += 1
        outbound[source] += 1

    entry_points = [
        p for p in paths
        if posixpath.basename(p) in ENTRY_NAMES or p in ("app/main.py", "src/main.ts", "src/main.tsx")
    ][:8]
    if not entry_points:
        entry_points = [p for p in paths if not _is_test(p)][:3]

    docs = [p for p, f in zip(paths, files) if f.get("is_doc")]
    hot_files = [{"path": p, "inbound": inbound[p], "outbound": outbound[p]}
                 for p in sorted(paths, key=lambda x: (inbound[x], outbound[x]), reverse=True)
                 if inbound[p] or outbound[p]][:10]

    reading: list[str] = []
    for candidate in [*entry_points, *[d for d in docs if d.lower().endswith("readme.md")],
                      *docs, *[h["path"] for h in hot_files]]:
        if candidate not in reading:
            reading.append(candidate)
        if len(reading) >= 12:
            break

    modules: dict[str, dict] = defaultdict(lambda: {"files": 0, "lines": 0, "symbols": 0})
    symbols_by_path: Counter[str] = Counter(s["path"] for s in symbols)
    for f in files:
        mod = _module_of(f["path"])
        modules[mod]["files"] += 1
        modules[mod]["lines"] += f.get("line_count") or 0
        modules[mod]["symbols"] += symbols_by_path.get(f["path"], 0)
    module_list = [
        {"module": name, **stats} for name, stats in
        sorted(modules.items(), key=lambda kv: kv[1]["files"], reverse=True)
    ][:20]

    degree = {p: inbound[p] + outbound[p] for p in paths}
    top_nodes = [p for p in sorted(paths, key=lambda x: degree[x], reverse=True) if degree[p]][:MAX_GRAPH_NODES]
    node_set = set(top_nodes)
    graph = {
        "nodes": top_nodes,
        "edges": [[s, t] for s, t in edges if s in node_set and t in node_set][:120],
    }

    kind_rank = {"class": 0, "interface": 0, "struct": 1, "function": 2, "method": 3}
    glossary = [
        {"name": s["name"], "kind": s["kind"], "path": s["path"],
         "line": s["line_start"], "signature": s.get("signature", "")[:160]}
        for s in sorted(
            symbols,
            key=lambda s: (kind_rank.get(s["kind"], 9), len(s["name"]), s["name"]),
        )[:MAX_GLOSSARY]
    ]

    return {
        "totals": {
            "files": len(files),
            "lines": sum(f.get("line_count") or 0 for f in files),
            "symbols": len(symbols),
            "dependencies": len(edges),
            "docs": len(docs),
            "tests": sum(1 for p in paths if _is_test(p)),
        },
        "languages": dict(sorted(languages.items(), key=lambda kv: kv[1], reverse=True)),
        "entry_points": entry_points,
        "hot_files": hot_files,
        "reading_order": reading,
        "modules": module_list,
        "graph": graph,
        "glossary": glossary,
    }
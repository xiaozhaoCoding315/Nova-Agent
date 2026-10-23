"""Verify file:line citations in an assistant answer against indexed files."""
import re

from app.db import query

_CITATION = re.compile(
    r"([\w./\\-]+\.(?:py|pyi|js|jsx|ts|tsx|vue|svelte|java|kt|scala|go|rs|c|h|cpp|hpp|cs|rb|php|sql|md|txt|yaml|yml|json|toml|ini|sh|ps1)):(\d+)(?:-\d+)?"
)


async def verify_citations(text: str, repo_ids: list[str], executed: bool) -> dict:
    """Return a citation report: which paths/lines exist, which don't.

    Statuses: verified | out_of_range | missing | unchecked (no repo scope).
    """
    seen: dict[tuple[str, int], dict] = {}
    for match in _CITATION.finditer(text or ""):
        path = match.group(1).replace("\\", "/").lstrip("./")
        line = int(match.group(2))
        seen[(path, line)] = {"path": path, "line": line}

    citations = list(seen.values())
    base = {"citations": citations, "executed": executed,
            "verified": 0, "missing": 0, "out_of_range": 0, "skipped": 0}
    if not citations:
        return base
    if not repo_ids:
        for c in citations:
            c["status"] = "unchecked"
        base["skipped"] = len(citations)
        return base

    rows = await query(
        "SELECT path, line_count FROM repo_files WHERE repo_id = ANY(%s::uuid[])",
        (repo_ids,),
    )
    files = {r[0]: r[1] or 0 for r in rows}

    for c in citations:
        raw = c["path"]
        match = raw if raw in files else None
        if match is None:
            candidates = [p for p in files if p.endswith("/" + raw) or p.endswith("/" + raw.split("/")[-1])]
            match = candidates[0] if candidates else None
        if match is None:
            c["status"] = "missing"
            base["missing"] += 1
            continue
        c["resolved_path"] = match
        line_count = files[match]
        if line_count and c["line"] > line_count:
            c["status"] = "out_of_range"
            base["out_of_range"] += 1
        else:
            c["status"] = "verified"
            base["verified"] += 1
    return base
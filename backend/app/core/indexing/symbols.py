"""Symbol extraction (Python via ast, others via brace-aware regex) and
symbol search over the ``symbols`` table."""
import ast
import re

import structlog

logger = structlog.get_logger()

MAX_SYMBOLS_PER_FILE = 500

_JAVA_LIKE_KINDS = [
    ("class", re.compile(r"^\s*(?:public|private|protected|abstract|final|static|sealed|export|declare|\s)*\bclass\s+([A-Za-z_]\w*)")),
    ("interface", re.compile(r"^\s*(?:public|private|protected|abstract|static|export|\s)*\binterface\s+([A-Za-z_]\w*)")),
    ("enum", re.compile(r"^\s*(?:public|private|protected|static|export|\s)*\b(?:enum|record)\s+([A-Za-z_]\w*)")),
    ("struct", re.compile(r"^\s*(?:pub\s+)?(?:type\s+)?\bstruct\s+([A-Za-z_]\w*)")),
]

_GO_STRUCT = re.compile(r"^\s*type\s+([A-Za-z_]\w*)\s+struct\b")

_JS_FUNCS = [
    ("function", re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s+([A-Za-z_$][\w$]*)\s*\(")),
    ("function", re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:function\b|\()")),
    ("method", re.compile(r"^\s{2,}(?:public|private|protected|static|readonly|async|get|set|\s)*([A-Za-z_$][\w$]*)\s*\([^)]*\)\s*(?::\s*[\w<>\[\],.\s|]+)?\{")) ,
]

_JAVA_METHOD = re.compile(
    r"^\s{2,}(?:public|private|protected|static|final|synchronized|abstract|default|native|\s)+"
    r"[\w<>\[\],.?\s]+\s+([A-Za-z_]\w*)\s*\([^;]*\)\s*(?:throws\s+[\w,.\s]+)?\{"
)

_GO_FUNC = re.compile(r"^\s*func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)\s*\(")

_RUST_FN = re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?fn\s+([A-Za-z_]\w*)")


def extract_symbols(content: str, lang: str, max_symbols: int = MAX_SYMBOLS_PER_FILE) -> list[dict]:
    """Return a list of {kind, name, parent, line_start, line_end, signature}."""
    try:
        if lang == "python":
            return _extract_python(content, max_symbols)
        return _extract_generic(content, lang, max_symbols)
    except Exception as exc:  # noqa: BLE001
        logger.debug("symbol_extraction_failed", lang=lang, error=str(exc))
        return []


def _extract_python(content: str, max_symbols: int) -> list[dict]:
    tree = ast.parse(content)
    lines = content.splitlines()
    symbols: list[dict] = []

    def visit(node, parent: str = "") -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                kind = "class" if isinstance(child, ast.ClassDef) else "method" if parent else "function"
                signature = lines[child.lineno - 1].strip() if child.lineno - 1 < len(lines) else ""
                symbols.append({
                    "kind": kind,
                    "name": child.name,
                    "parent": parent,
                    "line_start": child.lineno,
                    "line_end": getattr(child, "end_lineno", child.lineno),
                    "signature": signature[:300],
                })
                if len(symbols) >= max_symbols:
                    return
                if isinstance(child, ast.ClassDef):
                    visit(child, parent=child.name if not parent else f"{parent}.{child.name}")
            elif isinstance(child, (ast.If, ast.Try, ast.With, ast.For, ast.While)) and not parent:
                visit(child, parent)

    visit(tree)
    return symbols[:max_symbols]


def _brace_end(lines: list[str], start_idx: int) -> int:
    """Find the matching closing brace line for a declaration (1-based end)."""
    depth = 0
    started = False
    for i in range(start_idx, min(len(lines), start_idx + 400)):
        for ch in lines[i]:
            if ch == "{":
                depth += 1
                started = True
            elif ch == "}":
                depth -= 1
                if started and depth <= 0:
                    return i + 1
    return start_idx + 1


def _extract_generic(content: str, lang: str, max_symbols: int) -> list[dict]:
    lines = content.splitlines()
    patterns: list[tuple[str, re.Pattern]] = []

    if lang in ("javascript", "jsx", "typescript", "tsx", "vue", "svelte"):
        patterns = _JAVA_LIKE_KINDS[:2] + _JS_FUNCS
    elif lang == "java" or lang == "kotlin" or lang == "csharp" or lang == "scala":
        patterns = _JAVA_LIKE_KINDS + [("method", _JAVA_METHOD)]
    elif lang == "go":
        patterns = [("struct", _GO_STRUCT), ("function", _GO_FUNC)]
    elif lang == "rust":
        patterns = _JAVA_LIKE_KINDS[3:4] + [("function", _RUST_FN)]
    elif lang in ("c", "cpp"):
        patterns = _JAVA_LIKE_KINDS[3:4]
    else:
        return []

    symbols: list[dict] = []
    for idx, line in enumerate(lines):
        if len(symbols) >= max_symbols:
            break
        for kind, pattern in patterns:
            m = pattern.match(line)
            if not m:
                continue
            name = m.group(1) if m.groups() else ""
            if not name:
                continue
            if "{" in line and "}" not in line:
                end = _brace_end(lines, idx)
            else:
                end = idx + 1
            symbols.append({
                "kind": kind,
                "name": name,
                "parent": "",
                "line_start": idx + 1,
                "line_end": max(end, idx + 1),
                "signature": line.strip()[:300],
            })
            break
    return symbols


async def search_symbols(query: str, repo_ids: list[str] | None = None, limit: int = 8) -> list[dict]:
    """Ordered symbol lookup: exact name > prefix > substring, shortest first."""
    from app.db import query as db_query

    sql = """
        SELECT s.name, s.kind, f.path, s.line_start, s.line_end, COALESCE(s.signature, '')
        FROM symbols s JOIN repo_files f ON f.id = s.file_id
        WHERE s.name ILIKE %s
    """
    params: list = [f"%{query}%"]
    if repo_ids:
        sql += " AND s.repo_id = ANY(%s::uuid[])"
        params.append(repo_ids)
    sql += """
        ORDER BY (lower(s.name) = lower(%s)) DESC,
                 (s.name ILIKE %s) DESC,
                 length(s.name) ASC
        LIMIT %s
    """
    params.extend([query, f"{query}%", limit])

    rows = await db_query(sql, tuple(params))
    return [
        {
            "name": r[0], "kind": r[1], "path": r[2],
            "line_start": r[3] or 0, "line_end": r[4] or 0, "signature": r[5],
        }
        for r in rows
    ]
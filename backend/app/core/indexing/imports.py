"""Import extraction and resolution — the dependency graph behind impact
analysis and the repo brain."""
import ast
import posixpath
import re

_JS_IMPORT = re.compile(
    r"""(?:from\s+|require\(\s*|import\(\s*)\s*['"]([^'"]+)['"]"""
)
_JAVA_IMPORT = re.compile(r"^\s*import\s+(?:static\s+)?([\w.]+)\s*;", re.MULTILINE)

_JS_EXTS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".vue", ".svelte")


def extract_imports(content: str, lang: str) -> list[dict]:
    """Return raw import targets: [{"target": str, "kind": str}]."""
    if lang == "python":
        return _extract_python(content)
    if lang in ("javascript", "jsx", "typescript", "tsx", "vue", "svelte"):
        return [{"target": m, "kind": "import"} for m in _JS_IMPORT.findall(content)]
    if lang in ("java", "kotlin", "scala"):
        return [{"target": m, "kind": "import"} for m in _JAVA_IMPORT.findall(content)]
    return []


def _extract_python(content: str) -> list[dict]:
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return []
    out: list[dict] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.extend({"target": alias.name, "kind": "import"} for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            level = node.level or 0
            module = node.module or ""
            if module:
                out.append({"target": "." * level + module, "kind": "from"})
            elif level:
                # `from . import a, b` — each name is a submodule
                out.extend({"target": "." * level + alias.name, "kind": "from"} for alias in node.names)
    return out


def _python_candidates(target: str, from_path: str) -> list[str]:
    level = len(target) - len(target.lstrip("."))
    module = target.lstrip(".")
    parts = module.split(".") if module else []
    candidates: list[str] = []

    if level:
        base = from_path.split("/")[:-1]
        up = level - 1
        base = base[: len(base) - up] if up else base
        if parts:
            candidates.append("/".join(base + parts))
        else:
            candidates.append("/".join(base))
    else:
        candidates.append("/".join(parts))

    out: list[str] = []
    for cand in filter(None, candidates):
        out.append(cand + ".py")
        out.append(cand + "/__init__.py")
    return out


def _js_candidates(target: str, from_path: str) -> list[str]:
    if not target.startswith("."):
        return []  # bare package — external
    base = posixpath.normpath(posixpath.join(posixpath.dirname(from_path), target))
    candidates = [base]
    candidates.extend(base + ext for ext in _JS_EXTS)
    candidates.extend(f"{base}/index{ext}" for ext in _JS_EXTS)
    return candidates


def _java_candidates(target: str) -> list[str]:
    return [target.replace(".", "/") + ".java"]


def resolve_import(
    target: str,
    from_path: str,
    kind: str,
    path_set: set[str],
    suffix_index: dict[str, str],
) -> str | None:
    """Map an import target to a repo file path, or None when external."""
    ext = posixpath.splitext(from_path)[1].lower()
    if ext == ".py":
        candidates = _python_candidates(target, from_path)
    elif ext in (".java", ".kt", ".scala"):
        candidates = _java_candidates(target)
    elif ext in _JS_EXTS:
        candidates = _js_candidates(target, from_path)
    else:
        return None

    for cand in candidates:
        normalized = posixpath.normpath(cand)
        if normalized in path_set:
            return normalized
        if normalized in suffix_index:
            return suffix_index[normalized]
    return None


def build_path_index(paths: list[str]) -> tuple[set[str], dict[str, str]]:
    """Exact path set + suffix index so Java-style package paths resolve."""
    path_set = set(paths)
    suffix_index: dict[str, str] = {}
    for path in paths:
        parts = path.split("/")
        for i in range(1, len(parts)):
            suffix = "/".join(parts[i:])
            suffix_index.setdefault(suffix, path)
    return path_set, suffix_index
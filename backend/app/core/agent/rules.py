"""Project rules for the system prompt.

Repo-level conventions live in AGENTS.md (CLAUDE.md is accepted as an
adapter). Builder projects may also have rules stored before the file exists.
"""
from app.core.security.paths import UnsafePathError, resolve_repo_path

MAX_RULES_PER_REPO = 4000
MAX_RULES_TOTAL = 8000
_RULE_FILES = ("AGENTS.md", "CLAUDE.md")


def _read_rule_file(root: str, name: str) -> str:
    try:
        target = resolve_repo_path(root, name)
    except UnsafePathError:
        return ""
    if not target.is_file():
        return ""
    try:
        return target.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def load_repo_rules(repos: list[dict]) -> list[dict]:
    """Return [{repo, source, content}] bounded for prompt injection."""
    rules: list[dict] = []
    total = 0
    for repo in repos:
        root = str(repo.get("root_path") or "")
        if not root:
            continue
        content = ""
        source = ""
        for name in _RULE_FILES:
            content = _read_rule_file(root, name)
            if content:
                source = name
                break
        if not content:
            content = str(repo.get("rules") or "").strip()
            source = "项目约定"
        if not content:
            continue
        content = content[:MAX_RULES_PER_REPO]
        if total + len(content) > MAX_RULES_TOTAL:
            break
        total += len(content)
        rules.append({
            "repo": str(repo.get("name") or ""),
            "source": source,
            "content": content,
        })
    return rules

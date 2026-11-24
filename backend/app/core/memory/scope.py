"""Memory scopes.

Facts and daily summaries are never shared implicitly across product surfaces.
A dev conversation may read global + dev + its selected repos; a thesis
conversation may read global + that thesis project only.

Automatic extraction writes to the surface that produced the turn.  The one
exception is an explicit, stable cross-project preference (language, tone,
workflow habit), which the extractor may route to ``global``; project and
thesis facts always stay in their owning scope.
"""
from dataclasses import dataclass

GLOBAL = "global"
DEV = "dev"
THESIS = "thesis"
REPO = "repo"
AGENT = "agent"

VALID_TYPES = {GLOBAL, DEV, THESIS, REPO, AGENT}


@dataclass(frozen=True)
class Scope:
    type: str
    id: str = ""

    @property
    def label(self) -> str:
        if self.type == GLOBAL:
            return "全局"
        if self.type == THESIS:
            return "论文项目"
        if self.type == REPO:
            return "仓库"
        if self.type == AGENT:
            return "子代理"
        return "开发"


def normalize(scope_type: str | None, scope_id: str | None = "") -> Scope:
    kind = (scope_type or GLOBAL).strip().lower()
    if kind not in VALID_TYPES:
        kind = GLOBAL
    return Scope(kind, (scope_id or "").strip())


def extraction_scope(
    session: dict, repo_ids: list[str] | None = None
) -> Scope | None:
    """Where a turn's extracted facts belong; ``None`` means do not extract."""
    mode = (session.get("product_mode") or DEV).strip().lower()
    if mode == THESIS:
        project_id = str(session.get("thesis_project_id") or "").strip()
        if not project_id:
            # A thesis session without a project has no safe shared bucket.
            return None
        return Scope(THESIS, project_id)
    unique_repos = list(dict.fromkeys(str(r) for r in (repo_ids or []) if r))
    if len(unique_repos) == 1:
        # A single-repo dev conversation learns repo-local facts; a multi-repo
        # or repo-less one can only learn dev-wide facts.
        return Scope(REPO, unique_repos[0])
    return Scope(DEV, "")


def session_scope_filter(scope: Scope, alias: str = "s") -> tuple[str, list]:
    """SQL restricting sessions to the ones that belong to ``scope``.

    Episodic memory has no per-row scope column: a message inherits the
    session's product surface.  Global scope has no episodic equivalent and
    must not silently match every session.
    """
    if scope.type == THESIS:
        return (
            f"AND {alias}.product_mode = 'thesis' "
            f"AND {alias}.thesis_project_id::text = %s",
            [scope.id],
        )
    if scope.type == REPO:
        return (
            f"AND {alias}.product_mode = 'dev' AND ("
            f"  SELECT COUNT(*) FROM session_repos sr2 "
            f"  WHERE sr2.session_id = {alias}.id"
            f") = 1 AND EXISTS ("
            f"  SELECT 1 FROM session_repos sr "
            f"  WHERE sr.session_id = {alias}.id AND sr.repo_id::text = %s)",
            [scope.id],
        )
    if scope.type == DEV:
        return f"AND {alias}.product_mode = 'dev'", []
    return "AND FALSE", []


def session_scope_clause(
    scopes: list[Scope] | None, alias: str = "s",
) -> tuple[str, list]:
    """OR-combine readable session scopes; global contributes nothing."""
    if scopes is None:
        return "", []
    parts: list[str] = []
    params: list = []
    for scope in scopes:
        sql, values = session_scope_filter(scope, alias)
        if not sql or sql.strip() == "AND FALSE":
            continue
        parts.append(f"({sql.strip()[4:]})")
        params.extend(values)
    if not parts:
        return " AND FALSE", []
    return " AND (" + " OR ".join(parts) + ")", params


def readable_scopes(session: dict, repo_ids: list[str] | None = None) -> list[Scope]:
    """Scopes a turn may read, most specific last."""
    scopes = [Scope(GLOBAL, "")]
    extract = extraction_scope(session)
    if extract:
        scopes.append(extract)
    if (session.get("product_mode") or DEV) != THESIS:
        seen = {scope.id for scope in scopes if scope.type == REPO}
        for repo_id in repo_ids or []:
            value = str(repo_id)
            if value and value not in seen:
                scopes.append(Scope(REPO, value))
                seen.add(value)
    return scopes

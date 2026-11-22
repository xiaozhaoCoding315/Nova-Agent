"""Long-term memory (facts): extraction, dedup, retrieval, decay."""
import hashlib
import json
import math
import re
from datetime import date

import structlog

from app.config import settings
from app.core.memory import scope as scope_mod
from app.core.memory import vector_store
from app.core.security.redaction import redact_text
from app.db import execute, query

logger = structlog.get_logger()

DEDUP_COSINE_THRESHOLD = 0.92
CONFLICT_COSINE_THRESHOLD = 0.85
DEFAULT_TTL_DAYS = 90
DECAY_IDLE_DAYS = 7
DECAY_AMOUNT = 0.01
MIN_IMPORTANCE = 0.1
MAX_FACTS_PER_SCOPE = 500
MAX_FACTS_PER_USER = MAX_FACTS_PER_SCOPE  # compatibility for callers/tests
CANDIDATE_LIMIT = 1000
MAX_DECAY_DAYS = 30

STATUS_ACTIVE = "active"
STATUS_SUPERSEDED = "superseded"
STATUS_ARCHIVED = "archived"
VALID_STATUSES = {STATUS_ACTIVE, STATUS_SUPERSEDED, STATUS_ARCHIVED}

CATEGORY_FACT = "fact"
CATEGORY_PREFERENCE = "preference"
CATEGORY_PROJECT = "project"
CATEGORY_DECISION = "decision"
CATEGORY_CORRECTION = "correction"
VALID_CATEGORIES = {
    CATEGORY_FACT, CATEGORY_PREFERENCE, CATEGORY_PROJECT,
    CATEGORY_DECISION, CATEGORY_CORRECTION,
}
GLOBAL_CATEGORIES = {CATEGORY_PREFERENCE, CATEGORY_CORRECTION}

_PREFERENCE_CUE = re.compile(
    r"(以后|今后|从现在开始|总是|一直|习惯|偏好|喜欢|记住|请用|别再|不要用|"
    r"\balways\b|\bnever\b|\bprefer\b|\bremember\b)",
    re.IGNORECASE,
)

_EXTRACT_PROMPT = """从下面这轮对话中提取值得长期记住的信息，例如用户偏好、项目背景、决策、习惯、明确要求。
只提取以后对话中有用的内容，不要提取一次性问题。输出 JSON 数组，没有则输出 []。
元素格式：{{"text": "一句话事实", "kind": "preference|project|decision|correction|fact", "scope": "global|current", "replaces": "被纠正的旧记忆片段（可选）"}}
规则：
- 稳定的跨项目用户偏好（语言、回答风格、常用工具、工作习惯）用 scope=global。
- 项目、仓库、论文相关内容一律 scope=current，即使看起来像偏好。
- 用户明确纠正旧说法时 kind=correction，并在 replaces 写旧内容的关键片段。
- 最多 5 条，每条不超过 500 字。
用户: {user}
助手: {assistant}"""


class FactDuplicateError(Exception):
    """A fact with the same content already exists in the scope."""


def _content_hash(content: str) -> str:
    normalized = re.sub(r"\s+", " ", content.strip().lower())
    return hashlib.md5(normalized.encode("utf-8")).hexdigest()


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _scope_filter(scopes: list[scope_mod.Scope] | None) -> tuple[str, list]:
    """SQL fragment restricting rows to the readable scopes."""
    if scopes is None:
        return "", []
    if not scopes:
        return " AND FALSE", []
    parts: list[str] = []
    params: list = []
    for scope in scopes:
        parts.append("(scope_type = %s AND scope_id = %s)")
        params.extend([scope.type, scope.id])
    return " AND (" + " OR ".join(parts) + ")", params


def _normalize_category(value: str | None) -> str:
    category = (value or CATEGORY_FACT).strip().lower()
    return category if category in VALID_CATEGORIES else CATEGORY_FACT


def _normalize_status(value: str | None, default: str = STATUS_ACTIVE) -> str:
    status = (value or default).strip().lower()
    return status if status in VALID_STATUSES else default


def has_preference_cue(text: str) -> bool:
    """True when the user states a lasting preference, not a one-off request."""
    return bool(_PREFERENCE_CUE.search(text or ""))


def parse_extraction_items(raw: str) -> list[dict]:
    """Parse the extractor output, accepting both objects and legacy strings."""
    match = re.search(r"\[.*\]", raw or "", re.DOTALL)
    if not match:
        return []
    try:
        items = json.loads(match.group())
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(items, list):
        return []
    parsed: list[dict] = []
    for item in items:
        if isinstance(item, str):
            text = item.strip()
            if text:
                parsed.append({
                    "text": text, "kind": CATEGORY_FACT, "scope": "current",
                })
            continue
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        entry = {
            "text": text,
            "kind": _normalize_category(str(item.get("kind") or CATEGORY_FACT)),
            "scope": str(item.get("scope") or "current").strip().lower(),
        }
        replaces = str(item.get("replaces") or "").strip()[:200]
        if replaces:
            entry["replaces"] = replaces
        parsed.append(entry)
    return parsed


def resolve_fact_scope(
    item: dict, default: scope_mod.Scope, user_text: str
) -> scope_mod.Scope:
    """Only explicit, stable cross-project preferences escape the turn scope."""
    kind = _normalize_category(str(item.get("kind") or CATEGORY_FACT))
    wants_global = str(item.get("scope") or "").strip().lower() == "global"
    if wants_global and kind in GLOBAL_CATEGORIES and has_preference_cue(user_text):
        return scope_mod.Scope(scope_mod.GLOBAL, "")
    return default


async def _find_fact_by_hint(
    user_id: int, scope: scope_mod.Scope, hint: str
) -> int | None:
    if not hint:
        return None
    rows = await query(
        "SELECT id FROM facts WHERE user_id = %s AND scope_type = %s "
        "AND scope_id = %s AND status = 'active' AND content ILIKE %s "
        "ORDER BY last_used_at DESC LIMIT 1",
        (user_id, scope.type, scope.id, f"%{hint}%"),
    )
    return int(rows[0][0]) if rows else None


async def _find_conflict(
    user_id: int,
    embedding: list[float] | None,
    scope: scope_mod.Scope,
    category: str,
    exclude_id: int | None = None,
) -> tuple[int, int] | None:
    """A near-similar preference that the new fact is correcting.

    Returns ``(fact_id, version)``.  Exact duplicates are handled earlier; the
    window below duplicate level is deliberately narrow to avoid folding
    unrelated preferences into one another.
    """
    if not embedding or category not in GLOBAL_CATEGORIES:
        return None
    rows = await query(
        "SELECT id, embedding, version FROM facts WHERE user_id = %s "
        "AND scope_type = %s AND scope_id = %s AND status = 'active' "
        "AND category = %s AND embedding IS NOT NULL AND id <> %s "
        "ORDER BY last_used_at DESC LIMIT %s",
        (
            user_id, scope.type, scope.id, category, exclude_id or 0,
            CANDIDATE_LIMIT,
        ),
    )
    best: tuple[int, int] | None = None
    best_score = 0.0
    for fact_id, stored, version in rows:
        vec = _fact_embedding(stored)
        if not vec:
            continue
        cosine = _cosine(embedding, vec)
        if CONFLICT_COSINE_THRESHOLD <= cosine < DEDUP_COSINE_THRESHOLD:
            if cosine > best_score:
                best_score = cosine
                best = (int(fact_id), int(version or 1))
    return best


async def _supersede(user_id: int, fact_id: int) -> None:
    await execute(
        "UPDATE facts SET status = 'superseded', updated_at = now() "
        "WHERE id = %s AND user_id = %s",
        (fact_id, user_id),
    )


_FACT_COLUMNS = (
    "id, content, importance, ttl_days, promoted_at, last_used_at, created_at, "
    "scope_type, scope_id, source_session_id::text, source_message_id, "
    "confidence, category, status, version, supersedes_id, updated_at"
)


def _fact_from_row(row) -> dict:
    return {
        "id": row[0], "content": row[1], "importance": float(row[2] or 1.0),
        "ttl_days": int(row[3] or DEFAULT_TTL_DAYS),
        "promoted_at": row[4], "last_used_at": row[5], "created_at": row[6],
        "scope_type": row[7] or scope_mod.GLOBAL, "scope_id": row[8] or "",
        "source_session_id": row[9], "source_message_id": row[10],
        "confidence": float(row[11] or 1.0),
        "category": row[12] or CATEGORY_FACT, "status": row[13] or STATUS_ACTIVE,
        "version": int(row[14] or 1), "supersedes_id": row[15],
        "updated_at": row[16],
    }


async def get_fact(user_id: int, fact_id: int) -> dict | None:
    rows = await query(
        f"SELECT {_FACT_COLUMNS} FROM facts WHERE id = %s AND user_id = %s",
        (fact_id, user_id),
    )
    return _fact_from_row(rows[0]) if rows else None


async def list_facts(
    user_id: int,
    *,
    scope_type: str | None = None,
    scope_id: str | None = None,
    status: str | None = None,
    include_inactive: bool = False,
    limit: int = 200,
) -> list[dict]:
    clauses = ["user_id = %s"]
    params: list = [user_id]
    if scope_type:
        scope = scope_mod.normalize(scope_type, scope_id)
        clauses.append("scope_type = %s AND scope_id = %s")
        params.extend([scope.type, scope.id])
    if status and status.strip().lower() != "all":
        clauses.append("status = %s")
        params.append(_normalize_status(status))
    elif not include_inactive:
        clauses.append("status = 'active'")
    rows = await query(
        f"SELECT {_FACT_COLUMNS} FROM facts WHERE {' AND '.join(clauses)} "
        "ORDER BY (status = 'active') DESC, importance DESC, "
        "last_used_at DESC LIMIT %s",
        (*params, max(1, int(limit))),
    )
    return [_fact_from_row(row) for row in rows]


async def edit_fact(
    user_id: int,
    fact_id: int,
    *,
    content: str | None = None,
    importance: float | None = None,
    ttl_days: int | None = None,
    category: str | None = None,
    status: str | None = None,
) -> dict | None:
    """Edit a fact in place; content edits re-embed and bump the version."""
    rows = await query(
        "SELECT id, content, hash, scope_type, scope_id, version, status, category "
        "FROM facts WHERE id = %s AND user_id = %s",
        (fact_id, user_id),
    )
    if not rows:
        return None
    current = rows[0]
    scope = scope_mod.Scope(current[3] or scope_mod.GLOBAL, current[4] or "")
    updates: list[str] = []
    params: list = []
    embedding: list[float] | None = None

    if content is not None:
        clean = redact_text(content).strip()
        if not clean or len(clean) > 500:
            raise ValueError("记忆内容需为 1–500 字")
        new_hash = _content_hash(clean)
        duplicate = await query(
            "SELECT id FROM facts WHERE user_id = %s AND scope_type = %s "
            "AND scope_id = %s AND hash = %s AND id <> %s AND status = 'active'",
            (user_id, scope.type, scope.id, new_hash, fact_id),
        )
        if duplicate:
            raise FactDuplicateError("同范围已存在相同内容的记忆")
        try:
            from app.core.embedding.embedder import get_embedder
            embedding = (await get_embedder().embed([clean]))[0]
        except Exception:  # noqa: BLE001
            embedding = None
        updates.extend(["content = %s", "hash = %s", "embedding = %s"])
        params.extend([
            clean, new_hash, json.dumps(embedding) if embedding else None,
        ])
    if importance is not None:
        updates.append("importance = %s")
        params.append(max(MIN_IMPORTANCE, min(2.0, float(importance))))
    if ttl_days is not None:
        updates.append("ttl_days = %s")
        params.append(max(1, min(3650, int(ttl_days))))
    if category is not None:
        updates.append("category = %s")
        params.append(_normalize_category(category))
    if status is not None:
        updates.append("status = %s")
        params.append(_normalize_status(status))

    if not updates:
        return await get_fact(user_id, fact_id)
    sql = (
        "UPDATE facts SET " + ", ".join(updates)
        + ", version = version + 1, updated_at = now() "
        "WHERE id = %s AND user_id = %s RETURNING id"
    )
    updated = await execute(sql, (*params, fact_id, user_id))
    if not updated:
        return None
    if embedding is not None:
        await vector_store.index_fact(fact_id, user_id, embedding)
    return await get_fact(user_id, fact_id)


async def fact_sources(user_id: int, fact_id: int) -> dict | None:
    """Provenance for a fact, including the memory it superseded."""
    rows = await query(
        "SELECT f.id, f.content, f.source_session_id::text, f.source_message_id, "
        "f.supersedes_id, s.title, m.role, m.content "
        "FROM facts f "
        "LEFT JOIN sessions s ON s.id = f.source_session_id "
        "LEFT JOIN messages m ON m.id = f.source_message_id "
        "WHERE f.id = %s AND f.user_id = %s",
        (fact_id, user_id),
    )
    if not rows:
        return None
    row = rows[0]
    result = {
        "fact_id": row[0], "content": row[1],
        "source_session": (
            {"id": row[2], "title": row[5]} if row[2] else None
        ),
        "source_message": (
            {"id": row[3], "role": row[6], "preview": (row[7] or "")[:300]}
            if row[3] else None
        ),
        "supersedes": None,
    }
    if row[4] is not None:
        old = await query(
            "SELECT id, content, status, version FROM facts "
            "WHERE id = %s AND user_id = %s",
            (row[4], user_id),
        )
        if old:
            result["supersedes"] = {
                "id": old[0][0], "content": old[0][1],
                "status": old[0][2], "version": old[0][3],
            }
    return result


def rank_fact_rows(
    query_vec: list[float] | None, rows: list[tuple], limit: int
) -> list[tuple[int, str, float]]:
    """Pure ranking used by retrieval and the offline memory evaluation."""
    if not query_vec:
        return [(r[0], r[1], float(r[3] or 1.0)) for r in rows][:limit]
    scored = []
    for row in rows:
        fact_id, content, stored, importance = row
        vec = _fact_embedding(stored)
        cosine = _cosine(query_vec, vec) if vec else 0.0
        score = 0.7 * cosine + 0.3 * min(float(importance or 1.0), 2.0) / 2.0
        scored.append((score, fact_id, content, float(importance or 1.0)))
    scored.sort(reverse=True)
    return [
        (fact_id, content, importance)
        for _, fact_id, content, importance in scored[:limit]
    ]


async def _is_semantic_duplicate(
    user_id: int, content: str, embedding: list[float] | None,
    scopes: list[scope_mod.Scope] | None = None,
) -> int | None:
    """Return the existing fact id when ``content`` is a near-duplicate."""
    if not embedding:
        return None
    scope_sql, scope_params = _scope_filter(scopes)
    rows = await query(
        "SELECT id, embedding FROM facts WHERE user_id = %s "
        "AND status = 'active' AND embedding IS NOT NULL "
        f"{scope_sql} ORDER BY last_used_at DESC LIMIT %s",
        (user_id, *scope_params, CANDIDATE_LIMIT),
    )
    for fact_id, stored in rows:
        try:
            vec = stored if isinstance(stored, list) else json.loads(stored)
            if _cosine(embedding, vec) >= DEDUP_COSINE_THRESHOLD:
                return int(fact_id)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
    return None


async def _record_fact_day(fact_id: int, day: date | None = None) -> None:
    """Remember that a fact was observed on a day (promotion evidence)."""
    try:
        await execute(
            "INSERT INTO fact_days (fact_id, day, count) VALUES (%s, %s, 1) "
            "ON CONFLICT (fact_id, day) DO UPDATE SET count = fact_days.count + 1",
            (fact_id, day or date.today()),
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("fact_day_record_failed", fact_id=fact_id, error=str(exc))


async def _reinforce(fact_id: int, user_id: int, amount: float) -> None:
    """Record reuse without letting retrieval inflate importance without bound."""
    await execute(
        "UPDATE facts SET last_used_at = now(), last_decayed_at = CURRENT_DATE, "
        "importance = LEAST(importance + %s, 2.0) WHERE id = %s AND user_id = %s",
        (amount, fact_id, user_id),
    )


async def add_fact(
    user_id: int,
    content: str,
    ttl_days: int = DEFAULT_TTL_DAYS,
    importance: float = 1.0,
    *,
    scope_type: str = scope_mod.GLOBAL,
    scope_id: str = "",
    source_session_id: str | None = None,
    source_message_id: int | None = None,
    confidence: float = 1.0,
    category: str = CATEGORY_FACT,
    supersedes_id: int | None = None,
) -> bool:
    """Store a fact; returns False when deduplicated or rejected."""
    content = redact_text(content).strip()
    if not content or len(content) > 500:
        return False
    scope = scope_mod.normalize(scope_type, scope_id)
    category = _normalize_category(category)

    content_hash = _content_hash(content)
    existing = await query(
        "SELECT id FROM facts WHERE user_id = %s AND scope_type = %s "
        "AND scope_id = %s AND hash = %s AND status = 'active'",
        (user_id, scope.type, scope.id, content_hash),
    )
    if existing:
        fact_id = int(existing[0][0])
        await execute(
            "UPDATE facts SET last_used_at = now(), last_decayed_at = CURRENT_DATE, "
            "importance = LEAST(importance + 0.1, 2.0), updated_at = now() "
            "WHERE user_id = %s AND scope_type = %s AND scope_id = %s AND hash = %s",
            (user_id, scope.type, scope.id, content_hash),
        )
        await _record_fact_day(fact_id)
        return False

    count_rows = await query(
        "SELECT COUNT(*) FROM facts WHERE user_id = %s AND scope_type = %s "
        "AND scope_id = %s AND status = 'active'",
        (user_id, scope.type, scope.id),
    )
    if count_rows and int(count_rows[0][0]) >= MAX_FACTS_PER_SCOPE:
        # The cap must not silently stop learning.  Evict the least valuable
        # fact in this scope (unpromoted first) to make room for the new one.
        await execute(
            "DELETE FROM facts WHERE id = ("
            "  SELECT id FROM facts WHERE user_id = %s AND scope_type = %s "
            "  AND scope_id = %s AND status = 'active' "
            "  ORDER BY (promoted_at IS NOT NULL) ASC, importance ASC, "
            "           last_used_at ASC, created_at ASC LIMIT 1"
            ") RETURNING id",
            (user_id, scope.type, scope.id),
        )
        logger.info("facts_cap_evicted", user_id=user_id, scope=scope.type)

    supersede_target: tuple[int, int] | None = None
    if supersedes_id is not None:
        old = await query(
            "SELECT id, status, version, scope_type, scope_id, content "
            "FROM facts WHERE id = %s AND user_id = %s AND status = 'active'",
            (supersedes_id, user_id),
        )
        if (
            old
            and old[0][3] == scope.type
            and (old[0][4] or "") == scope.id
        ):
            supersede_target = (int(old[0][0]), int(old[0][2] or 1))

    embedding = None
    try:
        from app.core.embedding.embedder import get_embedder
        embedding = (await get_embedder().embed([content]))[0]
    except Exception:  # noqa: BLE001
        pass  # embedding is a nice-to-have for dedup only

    # A correction is near-identical to what it replaces by nature, so an
    # explicit ``replaces`` target must bypass the near-duplicate guard.
    duplicate_id = None
    if supersede_target is None:
        duplicate_id = await _is_semantic_duplicate(
            user_id, content, embedding, [scope],
        )
    if duplicate_id:
        # Merging evidence into the existing row is the point of dedup:
        # otherwise repeated observations never promote the fact.
        await _reinforce(duplicate_id, user_id, 0.05)
        await _record_fact_day(duplicate_id)
        return False

    if supersede_target is None:
        supersede_target = await _find_conflict(
            user_id, embedding, scope, category,
        )
    version = 1
    superseded_id = None
    if supersede_target is not None:
        superseded_id, old_version = supersede_target
        version = old_version + 1
        await _supersede(user_id, superseded_id)

    rows = await execute(
        """
        INSERT INTO facts
        (user_id, content, hash, embedding, importance, ttl_days, scope_type,
         scope_id, source_session_id, source_message_id, confidence,
         category, status, version, supersedes_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (user_id, scope_type, scope_id, hash) DO NOTHING
        RETURNING id
        """,
        (
            user_id, content, content_hash,
            json.dumps(embedding) if embedding else None,
            importance, ttl_days, scope.type, scope.id,
            source_session_id, source_message_id, confidence,
            category, STATUS_ACTIVE, version, superseded_id,
        ),
    )
    fact_id = None
    if rows:
        fact_id = rows[0][0]
    else:
        # The unique index also covers archived/superseded rows.  Re-adding a
        # previously retired memory reactivates it instead of silently failing.
        fallback = await execute(
            "UPDATE facts SET status = 'active', version = version + 1, "
            "last_used_at = now(), last_decayed_at = CURRENT_DATE, "
            "updated_at = now() WHERE user_id = %s AND scope_type = %s "
            "AND scope_id = %s AND hash = %s RETURNING id",
            (user_id, scope.type, scope.id, content_hash),
        )
        if fallback:
            fact_id = fallback[0][0]
    if fact_id is not None:
        await _record_fact_day(fact_id)
        await vector_store.index_fact(int(fact_id), user_id, embedding)
    return True


def _fact_embedding(value) -> list[float] | None:
    if value is None:
        return None
    try:
        vec = value if isinstance(value, list) else json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return vec if isinstance(vec, list) else None


async def get_relevant_facts(
    user_id: int,
    query_text: str = "",
    limit: int = 8,
    scopes: list[scope_mod.Scope] | None = None,
) -> list[str]:
    """Rank facts by semantic relevance to the turn plus importance.

    All scoped facts (bounded by the per-scope cap) are candidates.  Ranking
    only the top 80 by importance used to hide newly learned or rarely used
    facts even when they were the most relevant.
    """
    scope_sql, scope_params = _scope_filter(scopes)
    query_vec: list[float] | None = None
    if query_text.strip():
        try:
            from app.core.embedding.embedder import get_embedder
            query_vec = (await get_embedder().embed([query_text[:2000]]))[0]
        except Exception as exc:  # noqa: BLE001
            logger.debug("fact_query_embedding_failed", error=str(exc))

    rows: list[tuple] | None = None
    if query_vec:
        # pgvector ranks the whole active corpus in PostgreSQL.  Only the
        # shortlist is fetched back, so this avoids a full JSONB scan.
        candidate_ids = await vector_store.rank_fact_ids(
            user_id, query_vec, scopes, limit=max(CANDIDATE_LIMIT, limit),
        )
        if candidate_ids is not None:
            if candidate_ids:
                placeholders = ",".join(["%s"] * len(candidate_ids))
                rows = await query(
                    "SELECT id, content, embedding, importance FROM facts "
                    f"WHERE user_id = %s AND status = 'active' "
                    f"AND id IN ({placeholders})",
                    (user_id, *candidate_ids),
                )
            else:
                rows = []
    if rows is None:
        order = (
            "importance DESC, last_used_at DESC"
            if not query_vec
            else "last_used_at DESC, importance DESC"
        )
        rows = await query(
            "SELECT id, content, embedding, importance FROM facts "
            f"WHERE user_id = %s AND status = 'active' {scope_sql} "
            f"ORDER BY {order} LIMIT %s",
            (user_id, *scope_params, CANDIDATE_LIMIT),
        )
    if not rows:
        return []

    selected = rank_fact_rows(query_vec, rows, limit)
    ids = tuple(item[0] for item in selected)
    if ids:
        # Retrieval records reuse but must not raise importance: otherwise the
        # same few facts are selected and reinforced forever.
        await execute(
            "UPDATE facts SET last_used_at = now(), last_decayed_at = CURRENT_DATE "
            f"WHERE user_id = %s AND id IN ({','.join(['%s'] * len(ids))})",
            (user_id, *ids),
        )
    return [item[1] for item in selected]


async def extract_facts_from_turn(
    user_id: int,
    user_text: str,
    assistant_text: str,
    *,
    scope_type: str = scope_mod.GLOBAL,
    scope_id: str = "",
    source_session_id: str | None = None,
    source_message_id: int | None = None,
    raise_on_error: bool = False,
) -> int:
    """Best-effort extraction.

    Swallows LLM/parse errors and returns 0 by default; durable job handlers
    pass ``raise_on_error=True`` so the job runner can retry.
    """
    if len(user_text) < 8:
        return 0
    try:
        from app.core.harness.runtime import execute_with_harness
        from app.core.llm.factory import get_llm
        from app.core.llm.usage import record_usage
        from app.core.security.limits import ensure_token_budget

        await ensure_token_budget(user_id=user_id)
        prompt = _EXTRACT_PROMPT.format(
            user=redact_text(user_text)[:1500],
            assistant=redact_text(assistant_text)[:1500],
        )

        async def _call() -> tuple[str, dict | None]:
            llm = await get_llm(user_id, purpose="utility")
            chunks: list[str] = []
            usage: dict | None = None
            async for event in llm.astream_with_tools(
                [{"role": "user", "content": prompt}], tools=[]
            ):
                if event.get("type") == "content":
                    chunks.append(event["content"])
                value = event.get("usage")
                if isinstance(value, dict):
                    usage = value
            return "".join(chunks), usage

        raw, usage = await execute_with_harness(
            _call, context="memory/extract", timeout=settings.llm_timeout,
            use_retry=False, use_circuit=False, fallback=lambda: ("", None),
        )
        await record_usage(user_id, None, usage, source="memory")
        items = parse_extraction_items(raw)
        default_scope = scope_mod.normalize(scope_type, scope_id)
        added = 0
        for item in items[:5]:
            target = resolve_fact_scope(item, default_scope, user_text)
            supersedes_id = None
            if item.get("replaces"):
                supersedes_id = await _find_fact_by_hint(
                    user_id, target, item["replaces"],
                )
            if await add_fact(
                user_id, item["text"],
                scope_type=target.type, scope_id=target.id,
                source_session_id=source_session_id,
                source_message_id=source_message_id,
                category=item["kind"],
                supersedes_id=supersedes_id,
            ):
                added += 1
        return added
    except Exception as exc:  # noqa: BLE001
        logger.debug("fact_extraction_failed", error=str(exc))
        if raise_on_error:
            raise
        return 0


async def run_cleanup() -> dict:
    """Hourly maintenance: daily idle decay + TTL expiry. Returns counts."""
    decayed = await execute(
        "UPDATE facts SET "
        "importance = GREATEST(%s, importance - %s * LEAST(GREATEST("
        "  CURRENT_DATE - last_decayed_at, 0), %s)), "
        "last_decayed_at = CURRENT_DATE "
        "WHERE last_used_at < now() - make_interval(days => %s) "
        "AND last_decayed_at < CURRENT_DATE AND importance > %s "
        "RETURNING id",
        (MIN_IMPORTANCE, DECAY_AMOUNT, MAX_DECAY_DAYS, DECAY_IDLE_DAYS, MIN_IMPORTANCE),
    )
    # TTL counts from the last real use, not creation: a fact used yesterday
    # must not expire merely because it was first learned 90 days ago.
    deleted = await execute(
        "DELETE FROM facts WHERE "
        "GREATEST(created_at, last_used_at) + make_interval(days => ttl_days) < now() "
        "OR importance <= %s RETURNING id",
        (MIN_IMPORTANCE,),
    )
    indexed = await vector_store.backfill(limit=200)
    return {
        "facts_decayed": len(decayed) if isinstance(decayed, list) else 0,
        "facts_expired": len(deleted) if isinstance(deleted, list) else 0,
        "facts_indexed": indexed,
    }


async def promote_facts() -> int:
    """Promote facts observed on at least two distinct days."""
    rows = await execute(
        "UPDATE facts f SET importance = LEAST(f.importance + 0.3, 2.0), promoted_at = now() "
        "WHERE f.promoted_at IS NULL AND f.id IN ("
        "  SELECT fact_id FROM fact_days GROUP BY fact_id HAVING COUNT(DISTINCT day) >= 2"
        ") RETURNING f.id"
    )
    return len(rows) if isinstance(rows, list) else 0

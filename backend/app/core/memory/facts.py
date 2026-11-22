"""Long-term memory (facts): extraction, dedup, retrieval, decay."""
import hashlib
import json
import math
import re
from datetime import date

import structlog

from app.config import settings
from app.core.memory import scope as scope_mod
from app.core.security.redaction import redact_text
from app.db import execute, query

logger = structlog.get_logger()

DEDUP_COSINE_THRESHOLD = 0.92
DEFAULT_TTL_DAYS = 90
DECAY_IDLE_DAYS = 7
DECAY_AMOUNT = 0.01
MIN_IMPORTANCE = 0.1
MAX_FACTS_PER_SCOPE = 500
MAX_FACTS_PER_USER = MAX_FACTS_PER_SCOPE  # compatibility for callers/tests
CANDIDATE_LIMIT = 1000
MAX_DECAY_DAYS = 30

_EXTRACT_PROMPT = """从下面这轮对话中提取值得长期记住的"用户事实/偏好"，例如技术栈偏好、项目背景、习惯、明确要求。
只提取在以后对话中有用的信息，不要提取一次性问题。输出 JSON 数组，元素为字符串，没有则输出 []。
用户: {user}
助手: {assistant}"""


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


async def _is_semantic_duplicate(
    user_id: int, content: str, embedding: list[float] | None,
    scopes: list[scope_mod.Scope] | None = None,
) -> int | None:
    """Return the existing fact id when ``content`` is a near-duplicate."""
    if not embedding:
        return None
    scope_sql, scope_params = _scope_filter(scopes)
    rows = await query(
        "SELECT id, embedding FROM facts WHERE user_id = %s AND embedding IS NOT NULL "
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
) -> bool:
    """Store a fact; returns False when deduplicated or rejected."""
    content = redact_text(content).strip()
    if not content or len(content) > 500:
        return False
    scope = scope_mod.normalize(scope_type, scope_id)

    content_hash = _content_hash(content)
    existing = await query(
        "SELECT id FROM facts WHERE user_id = %s AND scope_type = %s "
        "AND scope_id = %s AND hash = %s",
        (user_id, scope.type, scope.id, content_hash),
    )
    if existing:
        fact_id = int(existing[0][0])
        await execute(
            "UPDATE facts SET last_used_at = now(), last_decayed_at = CURRENT_DATE, "
            "importance = LEAST(importance + 0.1, 2.0) "
            "WHERE user_id = %s AND scope_type = %s AND scope_id = %s AND hash = %s",
            (user_id, scope.type, scope.id, content_hash),
        )
        await _record_fact_day(fact_id)
        return False

    count_rows = await query(
        "SELECT COUNT(*) FROM facts WHERE user_id = %s AND scope_type = %s "
        "AND scope_id = %s",
        (user_id, scope.type, scope.id),
    )
    if count_rows and int(count_rows[0][0]) >= MAX_FACTS_PER_SCOPE:
        # The cap must not silently stop learning.  Evict the least valuable
        # fact in this scope (unpromoted first) to make room for the new one.
        await execute(
            "DELETE FROM facts WHERE id = ("
            "  SELECT id FROM facts WHERE user_id = %s AND scope_type = %s "
            "  AND scope_id = %s "
            "  ORDER BY (promoted_at IS NOT NULL) ASC, importance ASC, "
            "           last_used_at ASC, created_at ASC LIMIT 1"
            ") RETURNING id",
            (user_id, scope.type, scope.id),
        )
        logger.info("facts_cap_evicted", user_id=user_id, scope=scope.type)

    embedding = None
    try:
        from app.core.embedding.embedder import get_embedder
        embedding = (await get_embedder().embed([content]))[0]
    except Exception:  # noqa: BLE001
        pass  # embedding is a nice-to-have for dedup only

    duplicate_id = await _is_semantic_duplicate(
        user_id, content, embedding, [scope],
    )
    if duplicate_id:
        # Merging evidence into the existing row is the point of dedup:
        # otherwise repeated observations never promote the fact.
        await _reinforce(duplicate_id, user_id, 0.05)
        await _record_fact_day(duplicate_id)
        return False

    rows = await execute(
        """
        INSERT INTO facts
        (user_id, content, hash, embedding, importance, ttl_days, scope_type,
         scope_id, source_session_id, source_message_id, confidence)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (user_id, scope_type, scope_id, hash) DO NOTHING
        RETURNING id
        """,
        (
            user_id, content, content_hash,
            json.dumps(embedding) if embedding else None,
            importance, ttl_days, scope.type, scope.id,
            source_session_id, source_message_id, confidence,
        ),
    )
    fact_id = None
    if rows:
        fact_id = rows[0][0]
    else:
        fallback = await query(
            "SELECT id FROM facts WHERE user_id = %s AND scope_type = %s "
            "AND scope_id = %s AND hash = %s",
            (user_id, scope.type, scope.id, content_hash),
        )
        if fallback:
            fact_id = fallback[0][0]
    if fact_id is not None:
        await _record_fact_day(fact_id)
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
    order = (
        "importance DESC, last_used_at DESC"
        if not query_text.strip()
        else "last_used_at DESC, importance DESC"
    )
    rows = await query(
        "SELECT id, content, embedding, importance FROM facts "
        f"WHERE user_id = %s {scope_sql} ORDER BY {order} LIMIT %s",
        (user_id, *scope_params, CANDIDATE_LIMIT),
    )
    if not rows:
        return []

    ranked = [(r[0], r[1], float(r[3] or 1.0)) for r in rows]
    if query_text.strip():
        try:
            from app.core.embedding.embedder import get_embedder
            query_vec = (await get_embedder().embed([query_text[:2000]]))[0]
            scored = []
            for (fact_id, content, importance), row in zip(ranked, rows):
                vec = _fact_embedding(row[2])
                cosine = _cosine(query_vec, vec) if vec else 0.0
                score = 0.7 * cosine + 0.3 * min(importance, 2.0) / 2.0
                scored.append((score, fact_id, content, importance))
            ranked = [
                (fact_id, content, importance)
                for _, fact_id, content, importance in sorted(scored, reverse=True)
            ]
        except Exception as exc:  # noqa: BLE001
            logger.debug("fact_semantic_rank_failed", error=str(exc))

    selected = ranked[:limit]
    ids = tuple(item[0] for item in selected)
    if ids:
        # Retrieval records reuse but must not raise importance: otherwise the
        # same few facts are selected and reinforced forever.
        await execute(
            "UPDATE facts SET last_used_at = now(), last_decayed_at = CURRENT_DATE "
            f"WHERE id IN ({','.join(['%s'] * len(ids))})",
            ids,
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
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        if not match:
            return 0
        items = json.loads(match.group())
        added = 0
        for item in items[:5]:
            if isinstance(item, str) and await add_fact(
                user_id, item,
                scope_type=scope_type, scope_id=scope_id,
                source_session_id=source_session_id,
                source_message_id=source_message_id,
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
    return {
        "facts_decayed": len(decayed) if isinstance(decayed, list) else 0,
        "facts_expired": len(deleted) if isinstance(deleted, list) else 0,
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

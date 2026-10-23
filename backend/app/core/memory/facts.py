"""Long-term memory (facts): extraction, dedup, retrieval, decay."""
import hashlib
import json
import math
import re

import structlog

from app.config import settings
from app.db import execute, query

logger = structlog.get_logger()

DEDUP_COSINE_THRESHOLD = 0.92
DEFAULT_TTL_DAYS = 90
DECAY_IDLE_DAYS = 7
DECAY_AMOUNT = 0.01
MIN_IMPORTANCE = 0.1
MAX_FACTS_PER_USER = 500

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


async def _is_semantic_duplicate(user_id: int, content: str, embedding: list[float] | None) -> bool:
    if not embedding:
        return False
    rows = await query(
        "SELECT embedding FROM facts WHERE user_id = %s AND embedding IS NOT NULL "
        "ORDER BY last_used_at DESC LIMIT 80",
        (user_id,),
    )
    for (stored,) in rows:
        try:
            vec = stored if isinstance(stored, list) else json.loads(stored)
            if _cosine(embedding, vec) >= DEDUP_COSINE_THRESHOLD:
                return True
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
    return False


async def add_fact(user_id: int, content: str, ttl_days: int = DEFAULT_TTL_DAYS, importance: float = 1.0) -> bool:
    """Store a fact; returns False when deduplicated or rejected."""
    content = content.strip()
    if not content or len(content) > 500:
        return False

    content_hash = _content_hash(content)
    existing = await query(
        "SELECT 1 FROM facts WHERE user_id = %s AND hash = %s", (user_id, content_hash)
    )
    if existing:
        await execute(
            "UPDATE facts SET last_used_at = now(), importance = LEAST(importance + 0.1, 2.0) "
            "WHERE user_id = %s AND hash = %s",
            (user_id, content_hash),
        )
        return False

    count_rows = await query("SELECT COUNT(*) FROM facts WHERE user_id = %s", (user_id,))
    if count_rows and int(count_rows[0][0]) >= MAX_FACTS_PER_USER:
        logger.info("facts_cap_reached", user_id=user_id)
        return False

    embedding = None
    try:
        from app.core.embedding.embedder import get_embedder
        embedding = (await get_embedder().embed([content]))[0]
    except Exception:  # noqa: BLE001
        pass  # embedding is a nice-to-have for dedup only

    if await _is_semantic_duplicate(user_id, content, embedding):
        return False

    await execute(
        """
        INSERT INTO facts (user_id, content, hash, embedding, importance, ttl_days)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (user_id, hash) DO NOTHING
        """,
        (user_id, content, content_hash, json.dumps(embedding) if embedding else None, importance, ttl_days),
    )
    return True


async def get_relevant_facts(user_id: int, limit: int = 8) -> list[str]:
    rows = await query(
        "SELECT id, content FROM facts WHERE user_id = %s "
        "ORDER BY importance DESC, last_used_at DESC LIMIT %s",
        (user_id, limit),
    )
    if rows:
        ids = tuple(r[0] for r in rows)
        await execute(
            "UPDATE facts SET last_used_at = now(), importance = LEAST(importance + 0.1, 2.0) "
            f"WHERE id IN ({','.join(['%s'] * len(ids))})",
            ids,
        )
    return [r[1] for r in rows]


async def extract_facts_from_turn(user_id: int, user_text: str, assistant_text: str) -> int:
    """Best-effort extraction; never raises."""
    if len(user_text) < 8:
        return 0
    try:
        from app.core.harness.runtime import execute_with_harness
        from app.core.llm.factory import get_llm
        from app.core.llm.usage import record_usage
        from app.core.security.limits import ensure_token_budget

        await ensure_token_budget(user_id=user_id)
        prompt = _EXTRACT_PROMPT.format(user=user_text[:1500], assistant=assistant_text[:1500])

        async def _call() -> tuple[str, dict | None]:
            llm = get_llm()
            chunks = []
            usage = None
            async for event in llm.astream_with_tools(
                [{"role": "user", "content": prompt}], tools=[]
            ):
                if event.get("type") == "content":
                    chunks.append(event["content"])
                elif event.get("type") == "usage":
                    usage = event.get("usage")
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
            if isinstance(item, str) and await add_fact(user_id, item):
                added += 1
        return added
    except Exception as exc:  # noqa: BLE001
        logger.debug("fact_extraction_failed", error=str(exc))
        return 0


async def run_cleanup() -> dict:
    """Hourly maintenance: idle decay + TTL expiry. Returns counts."""
    decayed = await execute(
        "UPDATE facts SET importance = importance - %s "
        "WHERE last_used_at < now() - make_interval(days => %s) AND importance > %s "
        "RETURNING id",
        (DECAY_AMOUNT, DECAY_IDLE_DAYS, MIN_IMPORTANCE),
    )
    deleted = await execute(
        "DELETE FROM facts WHERE created_at + make_interval(days => ttl_days) < now() "
        "OR importance <= %s RETURNING id",
        (MIN_IMPORTANCE,),
    )
    return {
        "facts_decayed": len(decayed) if isinstance(decayed, list) else 0,
        "facts_expired": len(deleted) if isinstance(deleted, list) else 0,
    }
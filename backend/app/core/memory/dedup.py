"""Two-stage deduplication: Hash exact-match + Embedding semantic-match."""
import hashlib
from app.db import query
from app.core.embedding.embedder import get_embedder

_embedder = get_embedder()


def fact_hash(fact: str) -> str:
    normalized = fact.strip().lower().replace(" ", "").replace("，", ",").replace("。", ".")
    return hashlib.md5(normalized.encode()).hexdigest()


async def is_duplicate(fact: str, session_id: str = None, threshold: float = 0.92) -> bool:
    from app.core.memory.store import _ensure_table
    await _ensure_table()

    # Stage 1: Hash exact match
    rows = await query(
        "SELECT COUNT(*) FROM agent_facts WHERE fact = %s",
        (fact.strip(),),
    )
    if rows and rows[0][0] > 0:
        return True

    # Stage 2: Semantic similarity
    try:
        fact_embedding = (await _embedder.embed([fact]))[0]
        if session_id:
            rows = await query(
                "SELECT id, fact FROM agent_facts WHERE session_id = %s ORDER BY created_at DESC LIMIT 50",
                (session_id,),
            )
        else:
            rows = await query(
                "SELECT id, fact FROM agent_facts ORDER BY created_at DESC LIMIT 50"
            )
        if not rows:
            return False
        existing_texts = [r[1] for r in rows]
        existing_embeddings = await _embedder.embed(existing_texts)
        def cosine(a, b):
            dot = sum(x * y for x, y in zip(a, b))
            na = sum(x * x for x in a) ** 0.5
            nb = sum(x * x for x in b) ** 0.5
            return dot / (na * nb) if na and nb else 0
        for i, emb in enumerate(existing_embeddings):
            if cosine(fact_embedding, emb) >= threshold:
                return True
    except Exception:
        pass
    return False


async def dedup_facts(facts: list, session_id: str = None) -> list:
    unique = []
    for fact in facts:
        if not await is_duplicate(fact["fact"], session_id):
            unique.append(fact)
    return unique

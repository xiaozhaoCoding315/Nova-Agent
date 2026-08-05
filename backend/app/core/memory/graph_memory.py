"""Graph-aware memory integration: build Neo4j relationships when facts are stored."""
import asyncio
from app.db.neo4j import upsert_entity, upsert_relationship


async def integrate_fact_to_graph(session_id: str, fact: str, category: str):
    """When a new fact is stored, create/update Neo4j nodes and relationships."""
    # Create a Fact node
    fact_name = fact[:100]  # truncate for node name
    await upsert_entity(fact_name, "fact", f"session:{session_id}", content=fact[:500])

    # Link fact to its category
    await upsert_relationship(fact_name, category.upper(), "BELONGS_TO", f"session:{session_id}")

    # Find existing entities mentioned in the fact and link to them
    # Simple keyword matching against known entity types
    entity_keywords = {
        "framework": ["FastAPI", "Django", "Flask", "React", "Vue", "Spring", "Express", "Redis", "Kafka", "Docker", "Kubernetes", "PostgreSQL", "Neo4j", "Elasticsearch", "Pydantic", "SQLAlchemy"],
        "concept": ["依赖注入", "中间件", "路由", "异步", "并发", "缓存", "认证", "授权", "ORM", "迁移", "依赖", "注入", "装饰器", "钩子", "事件"],
        "language": ["Python", "JavaScript", "TypeScript", "Java", "Go", "Rust", "C++", "SQL", "HTML", "CSS"],
    }

    for etype, keywords in entity_keywords.items():
        for kw in keywords:
            if kw.lower() in fact.lower():
                await upsert_entity(kw, etype, "knowledge_base")
                await upsert_relationship(fact_name, kw, "RELATED_TO", f"session:{session_id}")


async def build_learning_trajectory(session_id: str):
    """Build FOLLOWS relationships between facts in chronological order to form a learning trajectory."""
    from app.core.memory.store import get_facts

    facts = await get_facts(session_id, limit=50)
    if len(facts) < 2:
        return

    # Link consecutive facts with FOLLOWS
    for i in range(len(facts) - 1):
        current = facts[i]["fact"][:100]
        next_fact = facts[i + 1]["fact"][:100]
        await upsert_relationship(current, next_fact, "FOLLOWS", f"session:{session_id}")


async def search_graph_memory(query: str, session_id: str = None, top_k: int = 10) -> list[dict]:
    """Search graph memory: find entities related to query, expand via relationships.

    Returns list of dicts with keys: id, content, source, score_type, score
    """
    if not query or not query.strip():
        return []
    from app.db.neo4j import multi_hop_search, _run_query_sync
    # 1. Multi-hop search from seed entities
    try:
        multi_hop_results = await multi_hop_search(query, top_k=top_k)
    except Exception:
        multi_hop_results = []
    # 2. If session_id provided, boost entities from user's historical facts
    session_boost = []
    if session_id:
        try:
            from app.core.memory.store import get_facts
            facts = await get_facts(session_id, limit=20)
            for f in facts:
                try:
                    r = await multi_hop_search(f["fact"][:50], top_k=3)
                    session_boost.extend(r)
                except Exception:
                    continue
        except Exception:
            pass
    # Merge: multi-hop first, then session boost, dedup by id
    seen = set()
    merged = []
    for item in multi_hop_results + session_boost:
        key = item.get("id", item.get("content", ""))[:100]
        if key not in seen:
            seen.add(key)
            merged.append(item)
    return merged[:top_k]

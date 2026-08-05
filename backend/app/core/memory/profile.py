"""Aggregate facts into a structured user profile."""
import asyncio
from app.db import query


async def get_user_profile() -> dict:
    rows = await query(
        "SELECT category, fact, importance, created_at FROM agent_facts ORDER BY importance DESC, created_at DESC"
    )
    profile = {
        "domains": [],
        "preferences": [],
        "learning": [],
        "style": [],
        "general": [],
        "total_facts": len(rows),
    }
    category_map = {"domain": "domains", "preference": "preferences", "learning": "learning", "style": "style"}
    for row in rows:
        cat = row[0] or "general"
        target = category_map.get(cat, "general")
        profile[target].append({"fact": row[1], "importance": row[2], "created_at": str(row[3])})
    return profile


async def get_profile_summary() -> str:
    profile = await get_user_profile()
    parts = []
    if profile["domains"]:
        items = ", ".join(f["fact"] for f in profile["domains"][:5])
        parts.append(f"擅长领域: {items}")
    if profile["preferences"]:
        items = ", ".join(f["fact"] for f in profile["preferences"][:5])
        parts.append(f"技术偏好: {items}")
    if profile["learning"]:
        items = ", ".join(f["fact"] for f in profile["learning"][:5])
        parts.append(f"学习记录: {items}")
    if profile["style"]:
        items = ", ".join(f["fact"] for f in profile["style"][:5])
        parts.append(f"代码风格: {items}")
    return "\n".join(parts) if parts else "暂无用户画像数据"


async def get_graph_memory_summary() -> dict:
    """Return graph memory statistics for the profile panel."""
    from app.db.neo4j import get_driver

    def _query():
        driver = get_driver()
        with driver.session(database="neo4j") as session:
            entities = session.run("MATCH (e:Entity) RETURN count(e) AS cnt").single()["cnt"]
            facts = session.run("MATCH (e:Entity {type: 'fact'}) RETURN count(e) AS cnt").single()["cnt"]
            rels = session.run("MATCH ()-[r:RELATES]->() RETURN count(r) AS cnt").single()["cnt"]
            follows = session.run("MATCH ()-[r:RELATES {type: 'FOLLOWS'}]->() RETURN count(r) AS cnt").single()["cnt"]
            related = session.run("MATCH ()-[r:RELATES {type: 'RELATED_TO'}]->() RETURN count(r) AS cnt").single()["cnt"]
        return {
            "total_entities": entities,
            "fact_nodes": facts,
            "total_relationships": rels,
            "learning_steps": follows,
            "knowledge_links": related,
        }

    return await asyncio.to_thread(_query)

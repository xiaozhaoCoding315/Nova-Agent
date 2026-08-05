import asyncio
from fastapi import APIRouter
from app.db.neo4j import get_driver

router = APIRouter()


@router.get("/graph/stats")
async def graph_stats():
    """Return graph statistics."""
    def _query():
        driver = get_driver()
        with driver.session(database="neo4j") as session:
            entity_count = session.run("MATCH (e:Entity) RETURN count(e) AS cnt").single()["cnt"]
            rel_count = session.run("MATCH ()-[r:RELATES]->() RETURN count(r) AS cnt").single()["cnt"]
            top = session.run(
                "MATCH (e:Entity) RETURN e.name AS name, e.type AS type, e.mention_count AS mentions "
                "ORDER BY e.mention_count DESC LIMIT 10"
            ).data()
            types = session.run(
                "MATCH (e:Entity) RETURN e.type AS type, count(e) AS cnt ORDER BY cnt DESC"
            ).data()
        return entity_count, rel_count, top, types

    entity_count, rel_count, top, types = await asyncio.to_thread(_query)
    return {
        "entity_count": entity_count,
        "relationship_count": rel_count,
        "top_entities": top,
        "type_distribution": types,
    }


@router.get("/graph/search")
async def graph_explore(entity: str, depth: int = 2):
    """Explore graph neighborhood of an entity."""
    def _search():
        driver = get_driver()
        with driver.session(database="neo4j") as session:
            result = session.run(
                f"""
                MATCH (e:Entity {{name: $name}})-[:RELATES*1..{depth}]-(related)
                RETURN related.name AS name, related.type AS type,
                       related.source AS source, length(path) AS hops
                LIMIT 20
                """,
                name=entity,
            )
            return result.data()

    neighbors = await asyncio.to_thread(_search)
    return {"entity": entity, "neighbors": neighbors}

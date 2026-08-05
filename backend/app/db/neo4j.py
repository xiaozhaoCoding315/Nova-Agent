"""Neo4j connection manager with graph operations."""
import asyncio
from neo4j import GraphDatabase, AsyncGraphDatabase
from app.config import settings

# Use sync driver for Windows compatibility
_driver = None
_async_driver = None


def get_driver():
    """Sync driver (for thread-pool execution)."""
    global _driver
    if _driver is None:
        _driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password)
        )
    return _driver


def _run_query_sync(cypher: str, **params) -> list:
    """Execute a Cypher query synchronously."""
    driver = get_driver()
    with driver.session(database="neo4j") as session:
        result = session.run(cypher, **params)
        return result.data()


def _run_write_sync(cypher: str, **params) -> list:
    """Execute a write Cypher query within a transaction."""
    driver = get_driver()
    with driver.session(database="neo4j") as session:
        result = session.execute_write(lambda tx: tx.run(cypher, **params).data())
        return result


# Public async wrappers that run sync Neo4j in thread pool

async def init_graph():
    """Create constraints and indexes."""
    try:
        await asyncio.to_thread(
            _run_query_sync,
            "CREATE CONSTRAINT entity_name_type IF NOT EXISTS FOR (e:Entity) REQUIRE (e.name, e.type) IS UNIQUE"
        )
    except Exception:
        pass
    try:
        await asyncio.to_thread(
            _run_query_sync,
            "CREATE FULLTEXT INDEX entityIndex IF NOT EXISTS FOR (e:Entity) ON EACH [e.name, e.content]"
        )
    except Exception:
        pass


async def upsert_entity(name: str, etype: str, source: str, content: str = ""):
    cypher = """
        MERGE (e:Entity {name: $name, type: $type})
        ON CREATE SET e.source = $source, e.content = $content, e.mention_count = 1
        ON MATCH SET e.mention_count = coalesce(e.mention_count, 0) + 1
    """
    return await asyncio.to_thread(_run_write_sync, cypher,
                                   name=name, type=etype, source=source, content=content[:500])


async def upsert_relationship(from_name: str, to_name: str, rel_type: str, source: str):
    cypher = """
        MATCH (a:Entity {name: $from_name})
        MATCH (b:Entity {name: $to_name})
        MERGE (a)-[r:RELATES {type: $rel_type}]->(b)
        ON CREATE SET r.source = $source, r.weight = 1
        ON MATCH SET r.weight = coalesce(r.weight, 0) + 1
    """
    return await asyncio.to_thread(_run_write_sync, cypher,
                                   from_name=from_name, to_name=to_name,
                                   rel_type=rel_type, source=source)


async def multi_hop_search(search_query: str, top_k: int = 10, max_depth: int = 2) -> list:
    """Multi-hop graph traversal."""
    def _search():
        driver = get_driver()
        with driver.session(database="neo4j") as session:
            # Seed via fulltext
            seeds = session.run(
                "CALL db.index.fulltext.queryNodes('entityIndex', $q) YIELD node, score "
                "RETURN node.name AS name, node.type AS type, node.content AS content, "
                "node.source AS source, score ORDER BY score DESC LIMIT $lim",
                q=search_query, lim=top_k,
            ).data()

            if not seeds:
                return []

            seed_names = [s["name"] for s in seeds]
            cypher = (
                "MATCH (e:Entity) WHERE e.name IN $names "
                "MATCH path = (e)-[:RELATES*1.." + str(max_depth) + "]-(related) "
                "RETURN related.name AS name, related.type AS type, "
                "related.content AS content, related.source AS source, "
                "length(path) AS hops ORDER BY hops ASC LIMIT $lim"
            )
            hops = session.run(cypher, names=seed_names, lim=top_k * 2).data()

            seen = set()
            results = []
            for item in seeds + hops:
                key = f"{item['name']}:{item.get('type', '')}"
                if key not in seen:
                    seen.add(key)
                    results.append({
                        "id": item["name"],
                        "content": item.get("content", item["name"])[:500],
                        "source": item.get("source", "graph"),
                        "score_type": "graph",
                        "score": 1.0 / (1 + item.get("hops", 0)),
                        "hops": item.get("hops", 0),
                    })
            return results[:top_k]

    return await asyncio.to_thread(_search)

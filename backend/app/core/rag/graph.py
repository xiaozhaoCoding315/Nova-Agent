from app.models.domain import RetrievedChunk
from app.db.neo4j import multi_hop_search


async def graph_search(query: str, top_k: int = 10) -> list[RetrievedChunk]:
    """Multi-hop graph retrieval with entity expansion."""
    results = await multi_hop_search(query, top_k=top_k, max_depth=2)
    return [
        RetrievedChunk(
            id=r["id"],
            content=r["content"],
            source=r["source"],
            score_type="graph",
            score=r["score"],
            metadata={"hops": r.get("hops", 0)},
        )
        for r in results
    ]

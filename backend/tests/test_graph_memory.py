import pytest
from app.core.memory.graph_memory import integrate_fact_to_graph, search_graph_memory

@pytest.mark.asyncio
async def test_integrate_creates_entity():
    await integrate_fact_to_graph("test-sess-gm", "我喜欢用FastAPI做后端", "preference")
    from app.db.neo4j import _run_query_sync
    result = _run_query_sync("MATCH (e:Entity) WHERE e.name CONTAINS 'FastAPI' RETURN e.name as name")
    assert any("FastAPI" in r["name"] for r in result)

@pytest.mark.asyncio
async def test_search_graph_memory():
    await integrate_fact_to_graph("search-test-gm", "FastAPI支持异步中间件", "learning")
    results = await search_graph_memory("FastAPI中间件", "search-test-gm", top_k=5)
    assert isinstance(results, list)

@pytest.mark.asyncio
async def test_search_empty_returns_empty():
    assert await search_graph_memory("", "s", 5) == []

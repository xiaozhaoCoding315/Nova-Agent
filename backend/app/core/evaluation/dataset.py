"""Evaluation dataset management: Golden Queries + results storage."""
import json
import asyncio
import psycopg
from app.config import settings


async def _ensure_tables():
    async with await psycopg.AsyncConnection.connect(settings.postgres_dsn) as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS eval_queries (
                    id SERIAL PRIMARY KEY,
                    query TEXT NOT NULL,
                    category VARCHAR(50) DEFAULT 'general',
                    relevant_chunk_ids JSONB DEFAULT '[]',
                    notes TEXT DEFAULT '',
                    created_at TIMESTAMPTZ DEFAULT now()
                )
            """)
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS eval_results (
                    id SERIAL PRIMARY KEY,
                    run_name VARCHAR(200),
                    eval_type VARCHAR(50),
                    query_id INTEGER,
                    query_text TEXT,
                    metrics JSONB DEFAULT '{}',
                    ragas_scores JSONB DEFAULT '{}',
                    answer TEXT DEFAULT '',
                    duration_ms FLOAT DEFAULT 0,
                    created_at TIMESTAMPTZ DEFAULT now()
                )
            """)
        await conn.commit()


async def add_golden_query(query: str, category: str = "general",
                          relevant_ids: list = None, notes: str = "") -> int:
    await _ensure_tables()
    async with await psycopg.AsyncConnection.connect(settings.postgres_dsn) as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO eval_queries (query, category, relevant_chunk_ids, notes) VALUES (%s, %s, %s, %s) RETURNING id",
                (query, category, psycopg.types.json.Json(relevant_ids or []), notes)
            )
            row = await cur.fetchone()
        await conn.commit()
    return row[0]


async def list_queries(category: str = None) -> list:
    await _ensure_tables()
    async with await psycopg.AsyncConnection.connect(settings.postgres_dsn) as conn:
        async with conn.cursor() as cur:
            if category:
                await cur.execute("SELECT id, query, category, relevant_chunk_ids, notes FROM eval_queries WHERE category = %s ORDER BY id", (category,))
            else:
                await cur.execute("SELECT id, query, category, relevant_chunk_ids, notes FROM eval_queries ORDER BY id")
            rows = await cur.fetchall()
    return [{"id": r[0], "query": r[1], "category": r[2], "relevant_ids": r[3], "notes": r[4]} for r in rows]


async def get_query(query_id: int) -> dict:
    await _ensure_tables()
    async with await psycopg.AsyncConnection.connect(settings.postgres_dsn) as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT id, query, category, relevant_chunk_ids, notes FROM eval_queries WHERE id = %s", (query_id,))
            r = await cur.fetchone()
    if not r:
        return None
    return {"id": r[0], "query": r[1], "category": r[2], "relevant_ids": r[3], "notes": r[4]}


async def delete_query(query_id: int) -> bool:
    await _ensure_tables()
    async with await psycopg.AsyncConnection.connect(settings.postgres_dsn) as conn:
        async with conn.cursor() as cur:
            await cur.execute("DELETE FROM eval_queries WHERE id = %s", (query_id,))
        await conn.commit()
    return True


async def save_eval_result(run_name: str, eval_type: str, query_id: int,
                          query_text: str, metrics: dict, ragas_scores: dict,
                          answer: str = "", duration_ms: float = 0) -> int:
    await _ensure_tables()
    async with await psycopg.AsyncConnection.connect(settings.postgres_dsn) as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO eval_results (run_name, eval_type, query_id, query_text, metrics, ragas_scores, answer, duration_ms) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                (run_name, eval_type, query_id, query_text,
                 psycopg.types.json.Json(metrics or {}),
                 psycopg.types.json.Json(ragas_scores or {}),
                 answer, duration_ms)
            )
            row = await cur.fetchone()
        await conn.commit()
    return row[0]


async def list_eval_results(run_name: str = None) -> list:
    await _ensure_tables()
    async with await psycopg.AsyncConnection.connect(settings.postgres_dsn) as conn:
        async with conn.cursor() as cur:
            if run_name:
                await cur.execute("SELECT id, run_name, eval_type, query_id, query_text, metrics, ragas_scores, answer, duration_ms, created_at FROM eval_results WHERE run_name = %s ORDER BY id", (run_name,))
            else:
                await cur.execute("SELECT id, run_name, eval_type, query_id, query_text, metrics, ragas_scores, answer, duration_ms, created_at FROM eval_results ORDER BY id DESC LIMIT 100")
            rows = await cur.fetchall()
    return [{
        "id": r[0], "run_name": r[1], "eval_type": r[2], "query_id": r[3],
        "query_text": r[4], "metrics": r[5], "ragas_scores": r[6],
        "answer": r[7], "duration_ms": r[8], "created_at": str(r[9])
    } for r in rows]


async def get_eval_run_summary(run_name: str) -> dict:
    """Aggregate metrics for a named evaluation run."""
    await _ensure_tables()
    async with await psycopg.AsyncConnection.connect(settings.postgres_dsn) as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT COUNT(*), AVG(duration_ms) FROM eval_results WHERE run_name = %s",
                (run_name,)
            )
            row = await cur.fetchone()
            total = row[0]
            avg_dur = row[1] or 0.0

            await cur.execute(
                "SELECT metrics, ragas_scores FROM eval_results WHERE run_name = %s",
                (run_name,)
            )
            all_rows = await cur.fetchall()

    agg_metrics: dict[str, list] = {}
    agg_ragas: dict[str, list] = {}
    for metrics_blob, ragas_blob in all_rows:
        if metrics_blob:
            for k, v in metrics_blob.items():
                agg_metrics.setdefault(k, []).append(v)
        if ragas_blob:
            for k, v in ragas_blob.items():
                agg_ragas.setdefault(k, []).append(v)

    avg_metrics = {k: round(sum(v) / len(v), 4) for k, v in agg_metrics.items()}
    avg_ragas = {k: round(sum(v) / len(v), 4) for k, v in agg_ragas.items()}

    return {
        "run_name": run_name,
        "total_queries": total,
        "avg_duration_ms": round(avg_dur, 1),
        "avg_metrics": avg_metrics,
        "avg_ragas": avg_ragas,
    }


async def get_dataset_stats() -> dict:
    await _ensure_tables()
    async with await psycopg.AsyncConnection.connect(settings.postgres_dsn) as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT COUNT(*) FROM eval_queries")
            query_count = (await cur.fetchone())[0]
            await cur.execute("SELECT COUNT(DISTINCT run_name) FROM eval_results")
            run_count = (await cur.fetchone())[0]
            await cur.execute("SELECT category, COUNT(*) FROM eval_queries GROUP BY category")
            by_cat = {r[0]: r[1] for r in await cur.fetchall()}
    return {"golden_queries": query_count, "eval_runs": run_count, "by_category": by_cat}


async def seed_sample_queries():
    """Seed 10 sample Golden Queries for programmer tech Q&A."""
    samples = [
        ("FastAPI中间件怎么用？", "framework", [], "中间件注册和使用"),
        ("Python依赖注入是什么意思？", "concept", [], "DI概念和实现"),
        ("PostgreSQL怎么创建向量扩展？", "database", [], "pgvector安装"),
        ("Neo4j图数据库如何查询节点关系？", "database", [], "Cypher关系查询"),
        ("RAG检索的RRF融合算法是什么？", "algorithm", [], "倒数排名融合"),
        ("Docker容器如何限制资源？", "devops", [], "容器资源隔离"),
        ("React的useEffect依赖数组如何设置？", "framework", [], "React Hooks"),
        ("Redis缓存穿透怎么解决？", "architecture", [], "缓存设计"),
        ("FastAPI的ValidationError怎么处理？", "error", [], "Pydantic校验错误"),
        ("什么是DAG有向无环图？", "algorithm", [], "图论基础"),
    ]
    count = 0
    for query, category, rel_ids, notes in samples:
        await add_golden_query(query, category, rel_ids, notes)
        count += 1
    return count

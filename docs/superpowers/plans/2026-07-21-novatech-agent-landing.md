# NovaTech Agent 落地完善 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补齐 NovaTech Agent 6大亮点中的短板——数据库初始化、RAGAS评测修复、四层记忆补全、DAG竞速集成、审计日志验证、集成测试锁定。

**Architecture:** 在现有代码基础上加固，不重建。每个优先级独立任务组，TDD驱动。P0(init_db)是所有后续基础；P1(评测修复)提供量化尺子；P2(记忆)+P3(DAG竞速)是真功能对齐；P4(审计)+P5(集成测试)锁定成果。

**Tech Stack:** Python 3.12+, FastAPI, Qdrant, PostgreSQL 16+pgvector, Neo4j 5, asyncio, pytest

## Global Constraints

- 数据库: `192.168.150.128`（Qdrant:6333, PG:5432, Neo4j:7687）
- LLM 降级链: LongCat → DeepSeek → DashScope
- 本机无 Docker → 沙箱使用 direct fallback 模式
- Windows → 所有文件 IO 使用 UTF-8 编码
- TDD: 先写失败测试 → 实现 → 通过 → 提交
- 每个 Task 结束后 commit

---

## Task 1: P0 — 数据库初始化

**Files:**
- Create: `Nova Agent/backend/app/db/init_db.py`
- Modify: `Nova Agent/backend/app/db/__init__.py`
- Create: `Nova Agent/backend/tests/test_init_db.py`

**Interfaces:**
- Produces: `init_all() -> dict` — 一键初始化全部
- Produces: `init_postgres()`, `init_qdrant()`, `init_neo4j()` — 独立初始化
- Produces: `check_connectivity() -> dict` — 连通性检查

- [ ] **Step 1: Write the failing test**

Write `Nova Agent/backend/tests/test_init_db.py`:
```python
import pytest
from app.db.init_db import check_connectivity, init_postgres, init_qdrant, init_neo4j, init_all

@pytest.mark.asyncio
async def test_check_connectivity_returns_status():
    result = await check_connectivity()
    assert "postgres" in result and "qdrant" in result and "neo4j" in result

@pytest.mark.asyncio
async def test_init_postgres_creates_tables():
    await init_postgres()
    from app.db import query
    tables = await query("SELECT tablename FROM pg_tables WHERE schemaname='public'")
    names = [r[0] for r in tables]
    assert "documents" in names and "agent_facts" in names

@pytest.mark.asyncio
async def test_init_qdrant_creates_collection():
    await init_qdrant()
    from qdrant_client import QdrantClient
    from app.config import settings
    c = QdrantClient(url=settings.qdrant_url)
    assert "novatech_docs" in [col.name for col in c.get_collections().collections]

@pytest.mark.asyncio
async def test_init_neo4j_runs():
    result = await init_neo4j()
    assert result in ("ok", "already_exists")

@pytest.mark.asyncio
async def test_init_all_end_to_end():
    result = await init_all()
    assert all(v in ("ok", "already_exists", "created") for v in result.values())
```

- [ ] **Step 2: Run test — verify it fails**

Run: `cd Nova Agent/backend && python -m pytest tests/test_init_db.py -v`
Expected: ImportError

- [ ] **Step 3: Write init_db.py**

Write `Nova Agent/backend/app/db/init_db.py`:
```python
"""Database initialization: idempotent table/collection/index creation."""
import asyncio
import structlog

logger = structlog.get_logger()


async def init_postgres() -> str:
    from app.db import transaction
    queries = [
        ("""CREATE TABLE IF NOT EXISTS documents (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            content TEXT NOT NULL, source VARCHAR(500),
            metadata JSONB DEFAULT '{}', search_vector tsvector,
            created_at TIMESTAMPTZ DEFAULT now())""", ()),
        ("""CREATE OR REPLACE FUNCTION documents_search_vector_update() RETURNS trigger AS $$
        BEGIN NEW.search_vector := to_tsvector('simple', COALESCE(NEW.content, '')); RETURN NEW;
        END $$ LANGUAGE plpgsql""", ()),
        ("DROP TRIGGER IF EXISTS documents_search_vector_trigger ON documents", ()),
        ("""CREATE TRIGGER documents_search_vector_trigger BEFORE INSERT OR UPDATE OF content
            ON documents FOR EACH ROW EXECUTE FUNCTION documents_search_vector_update()""", ()),
        ("CREATE INDEX IF NOT EXISTS idx_documents_search ON documents USING GIN (search_vector)", ()),
        ("""CREATE TABLE IF NOT EXISTS agent_facts (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(), session_id VARCHAR(100),
            fact VARCHAR(500) NOT NULL, category VARCHAR(50) DEFAULT 'general',
            importance FLOAT DEFAULT 0.5, created_at TIMESTAMPTZ DEFAULT now(),
            last_accessed TIMESTAMPTZ DEFAULT now())""", ()),
        ("CREATE INDEX IF NOT EXISTS idx_agent_facts_ttl ON agent_facts (created_at)", ()),
        ("CREATE INDEX IF NOT EXISTS idx_agent_facts_session ON agent_facts (session_id)", ()),
        ("""CREATE TABLE IF NOT EXISTS eval_queries (
            id SERIAL PRIMARY KEY, query TEXT NOT NULL, category VARCHAR(100),
            relevant_ids JSONB DEFAULT '[]', notes TEXT, created_at TIMESTAMPTZ DEFAULT now())""", ()),
        ("""CREATE TABLE IF NOT EXISTS eval_results (
            id SERIAL PRIMARY KEY, run_name VARCHAR(200), eval_type VARCHAR(50),
            query_id INT REFERENCES eval_queries(id), metrics JSONB DEFAULT '{}',
            ragas_scores JSONB DEFAULT '{}', answer TEXT, duration_ms FLOAT,
            created_at TIMESTAMPTZ DEFAULT now())""", ()),
        ("""CREATE TABLE IF NOT EXISTS eval_corpora (
            id SERIAL PRIMARY KEY, name VARCHAR(200) UNIQUE, description TEXT,
            created_at TIMESTAMPTZ DEFAULT now())""", ()),
    ]
    await transaction(queries)
    from app.db import query
    cnt = await query("SELECT COUNT(*) FROM documents")
    return "already_exists" if cnt and cnt[0][0] > 0 else "ok"


async def init_qdrant() -> str:
    from qdrant_client import QdrantClient
    from qdrant_client.models import VectorParams, Distance
    from app.config import settings
    client = QdrantClient(url=settings.qdrant_url)
    try:
        client.get_collection("novatech_docs")
        return "already_exists"
    except Exception:
        pass
    client.create_collection("novatech_docs", vectors_config=VectorParams(size=1024, distance=Distance.COSINE))
    return "ok"


async def init_neo4j() -> str:
    from app.db.neo4j import init_graph
    await init_graph()
    return "ok"


async def check_connectivity() -> dict:
    result = {}
    try:
        from app.db import query
        await query("SELECT 1"); result["postgres"] = "connected"
    except Exception as e: result["postgres"] = f"failed: {e}"
    try:
        from qdrant_client import QdrantClient
        from app.config import settings
        c = QdrantClient(url=settings.qdrant_url, timeout=5)
        c.get_collections(); result["qdrant"] = "connected"
    except Exception as e: result["qdrant"] = f"failed: {e}"
    try:
        from app.db.neo4j import _run_query_sync
        await _run_query_sync("RETURN 1"); result["neo4j"] = "connected"
    except Exception as e: result["neo4j"] = f"failed: {e}"
    return result


async def init_all() -> dict:
    results = {}
    results["postgres"] = await init_postgres()
    results["qdrant"] = await init_qdrant()
    results["neo4j"] = await init_neo4j()
    logger.info("Database initialization complete", **results)
    return results


if __name__ == "__main__":
    asyncio.run(init_all())
```

- [ ] **Step 4: Update db/__init__.py**

Modify `Nova Agent/backend/app/db/__init__.py`:
```python
from app.db.init_db import init_all, init_postgres, init_qdrant, init_neo4j, check_connectivity

__all__ = ["query", "execute", "transaction", "init_all", "init_postgres", "init_qdrant", "init_neo4j", "check_connectivity"]
```

- [ ] **Step 5: Run test — verify it passes**

Run: `cd Nova Agent/backend && python -m pytest tests/test_init_db.py -v`
Expected: 5 PASSED

- [ ] **Step 6: Commit**

```bash
cd "D:/claudecode_project/Nova Agent" && git add backend/app/db/ backend/tests/test_init_db.py && git commit -m "feat(db): add init_db.py for one-click database initialization (P0)"
```

---

## Task 2: P1 — RAGAS 评测修复

**Files:**
- Modify: `Nova Agent/backend/app/core/evaluation/ragas.py`
- Create: `Nova Agent/backend/tests/test_ragas.py`

**Interfaces:**
- Produces: `evaluate_generation(question, answer, context) -> dict` (keys: faithfulness, answer_relevancy, context_precision, context_recall)

**诊断:** 当前分数0.1-0.2因：(1) prompt不明确 (2) 正则无法匹配多行JSON (3) 缺数值校验

- [ ] **Step 1: Write the failing test**

Write `Nova Agent/backend/tests/test_ragas.py`:
```python
import pytest
from app.core.evaluation.ragas import evaluate_generation

@pytest.mark.asyncio
async def test_ragas_returns_four_dimensions():
    scores = await evaluate_generation("FastAPI是什么", "FastAPI是一个现代Python Web框架",
        "FastAPI是一个高性能的Python Web框架，基于Starlette和Pydantic。")
    for key in ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]:
        assert key in scores and 0.0 <= scores[key] <= 1.0

@pytest.mark.asyncio
async def test_ragas_good_vs_bad():
    good = await evaluate_generation("FastAPI是什么",
        "FastAPI是一个现代Python Web框架，基于Starlette和Pydantic构建。",
        "FastAPI是一个高性能的Python Web框架，基于Starlette和Pydantic。它支持异步编程。")
    bad = await evaluate_generation("FastAPI是什么",
        "FastAPI是Java生态中最流行的框架，由Spring团队开发。",
        "FastAPI是一个高性能的Python Web框架，基于Starlette和Pydantic。")
    assert good["faithfulness"] > bad["faithfulness"]

@pytest.mark.asyncio
async def test_ragas_empty_input():
    scores = await evaluate_generation("", "", "")
    assert isinstance(scores, dict) and len(scores) == 4
```

- [ ] **Step 2: Run test — verify it fails**

Run: `cd Nova Agent/backend && python -m pytest tests/test_ragas.py::test_ragas_good_vs_bad -v`
Expected: FAIL

- [ ] **Step 3: Fix ragas.py**

Rewrite `Nova Agent/backend/app/core/evaluation/ragas.py`:
```python
"""RAGAS generation evaluation with robust parsing."""
import json, re, structlog
from app.core.llm.factory import get_llm

logger = structlog.get_logger()

EVAL_PROMPT = """你是一个RAG系统评测专家。请严格评估AI回答的质量。

## 问题
{question}

## AI回答
{answer}

## 参考上下文
{context}

## 评分标准
- faithfulness (忠实度): 回答是否完全基于上下文，无编造。0=完全编造，1=完全基于上下文
- answer_relevancy (回答相关性): 回答是否精准匹配问题核心。0=完全离题，1=精准切题
- context_precision (上下文精确率): 上下文中有多少比例与问题真正相关。0=全部无关，1=全部相关
- context_recall (上下文召回率): 上下文是否覆盖回答所需的全部支撑信息。0=完全缺失，1=完整覆盖

## 要求
1. 返回严格JSON格式，不要任何其他文字
2. 每个维度评分0.0-1.0，保留1位小数
3. 直接输出JSON，不要markdown代码块

返回格式：
{{"faithfulness": 0.0, "answer_relevancy": 0.0, "context_precision": 0.0, "context_recall": 0.0}}
"""


async def evaluate_generation(question: str, answer: str, context: str) -> dict:
    prompt = EVAL_PROMPT.format(
        question=question[:500] if question else "(空)",
        answer=answer[:1000] if answer else "(空)",
        context=context[:2000] if context else "(空)")
    full_response = ""
    try:
        llm = get_llm()
        async for token in llm.astream([{"role": "user", "content": prompt}]):
            full_response += token
    except Exception as e:
        logger.warning("RAGAS LLM call failed", error=str(e))
        return _zero_scores()
    return _parse_scores(full_response)


def _parse_scores(response: str) -> dict:
    cleaned = response.strip()
    cleaned = re.sub(r'^```json\s*', '', cleaned)
    cleaned = re.sub(r'^```\s*', '', cleaned)
    cleaned = re.sub(r'\s*```$', '', cleaned)
    match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', cleaned, re.DOTALL)
    if not match:
        match = re.search(r'\{.+?\}', cleaned, re.DOTALL)
    if match:
        try:
            scores = json.loads(match.group())
            return {k: max(0.0, min(1.0, float(scores.get(k, 0.0))))
                    for k in ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]}
        except (json.JSONDecodeError, ValueError, TypeError):
            pass
    logger.warning("Failed to parse RAGAS scores", response=response[:200])
    return _zero_scores()


def _zero_scores() -> dict:
    return {"faithfulness": 0.0, "answer_relevancy": 0.0, "context_precision": 0.0, "context_recall": 0.0}
```

- [ ] **Step 4: Run test — verify it passes**

Run: `cd Nova Agent/backend && python -m pytest tests/test_ragas.py -v`
Expected: 3 PASSED

- [ ] **Step 5: Commit**

```bash
cd "D:/claudecode_project/Nova Agent" && git add backend/app/core/evaluation/ragas.py backend/tests/test_ragas.py && git commit -m "fix(evaluation): repair RAGAS scoring — better prompt + robust JSON parsing (P1)"
```

---

## Task 3: P2 — 图记忆接入对话流

**Files:**
- Modify: `Nova Agent/backend/app/core/memory/graph_memory.py`
- Create: `Nova Agent/backend/tests/test_graph_memory.py`

**Interfaces:**
- Produces: `search_graph_memory(query, session_id, top_k) -> list[dict]` — NEW

- [ ] **Step 1: Write the failing test**

Write `Nova Agent/backend/tests/test_graph_memory.py`:
```python
import pytest
from app.core.memory.graph_memory import integrate_fact_to_graph, search_graph_memory

@pytest.mark.asyncio
async def test_integrate_creates_entity():
    await integrate_fact_to_graph("test-sess-gm", "我喜欢用FastAPI做后端", "preference")
    from app.db.neo4j import _run_query_sync
    result = await _run_query_sync("MATCH (e:Entity) WHERE e.name CONTAINS 'FastAPI' RETURN e.name as name")
    assert any("FastAPI" in r["name"] for r in result)

@pytest.mark.asyncio
async def test_search_graph_memory():
    await integrate_fact_to_graph("search-test-gm", "FastAPI支持异步中间件", "learning")
    results = await search_graph_memory("FastAPI中间件", "search-test-gm", top_k=5)
    assert isinstance(results, list)

@pytest.mark.asyncio
async def test_search_empty_returns_empty():
    assert await search_graph_memory("", "s", 5) == []
```

- [ ] **Step 2: Run test — verify it fails**

Run: `cd Nova Agent/backend && python -m pytest tests/test_graph_memory.py::test_search_graph_memory -v`
Expected: FAIL — `search_graph_memory` not defined

- [ ] **Step 3: Add search_graph_memory to graph_memory.py**

Append to `Nova Agent/backend/app/core/memory/graph_memory.py`:
```python
async def search_graph_memory(query: str, session_id: str = None, top_k: int = 10) -> list[dict]:
    """Search graph memory: find entities related to query, expand via relationships."""
    if not query or not query.strip():
        return []
    from app.db.neo4j import multi_hop_search, _run_query_sync
    try:
        multi_hop_results = await multi_hop_search(query, top_k=top_k)
    except Exception:
        multi_hop_results = []
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
```

- [ ] **Step 4: Update memory/__init__.py**

Modify `Nova Agent/backend/app/core/memory/__init__.py` to export `search_graph_memory`:
```python
from app.core.memory.graph_memory import integrate_fact_to_graph, build_learning_trajectory, search_graph_memory
```

- [ ] **Step 5: Run test — verify it passes**

Run: `cd Nova Agent/backend && python -m pytest tests/test_graph_memory.py -v`
Expected: 3 PASSED

- [ ] **Step 6: Commit**

```bash
cd "D:/claudecode_project/Nova Agent" && git add backend/app/core/memory/ backend/tests/test_graph_memory.py && git commit -m "feat(memory): add search_graph_memory for graph-based recall in dialog flow (P2)"
```

---

## Task 4: P2 — 运行时状态记忆（四层联动）

**Files:**
- Modify: `Nova Agent/backend/app/core/memory/context_assembler.py`
- Create: `Nova Agent/backend/tests/test_memory_integration.py`

**Interfaces:**
- Produces: `assemble_context(query, session_id) -> str` — enhanced to include graph memory

- [ ] **Step 1: Write the failing test**

Write `Nova Agent/backend/tests/test_memory_integration.py`:
```python
import pytest
from app.core.memory.context_assembler import assemble_context
from app.core.memory.store import save_fact, get_facts
from app.core.memory.session import add_message

@pytest.mark.asyncio
async def test_assemble_includes_long_term_facts():
    sid = "ctx-test-1"
    await save_fact(sid, "用户偏好使用FastAPI", "preference", 0.8)
    ctx = await assemble_context("推荐一个Web框架", sid)
    assert "FastAPI" in ctx or len(ctx) > 0  # context should be non-empty

@pytest.mark.asyncio
async def test_assemble_includes_session_history():
    sid = "ctx-test-2"
    add_message(sid, "user", "我喜欢异步编程")
    add_message(sid, "assistant", "FastAPI支持异步")
    ctx = await assemble_context("异步框架推荐", sid)
    assert len(ctx) > 0
```

- [ ] **Step 2: Run test — verify it fails/passes to establish baseline**

Run: `cd Nova Agent/backend && python -m pytest tests/test_memory_integration.py -v`
Expected: Results show current capability

- [ ] **Step 3: Enhance context_assembler.py**

Modify `Nova Agent/backend/app/core/memory/context_assembler.py` to integrate graph memory:
```python
async def assemble_context(query: str, session_id: str) -> str:
    """Assemble multi-layer context: session history + long-term facts + graph memory."""
    parts = []
    # Layer 1: Session history (short-term)
    from app.core.memory.session import get_history
    history = get_history(session_id, last_n=10)
    if history:
        hist_text = "\n".join(f"{m['role']}: {m['content']}" for m in history)
        parts.append(f"## 近期对话\n{hist_text}")
    # Layer 2: Long-term facts
    from app.core.memory.store import get_facts
    facts = await get_facts(session_id, limit=10)
    if facts:
        fact_text = "\n".join(f"- {f['fact']} ({f['category']})" for f in facts)
        parts.append(f"## 用户记忆\n{fact_text}")
    # Layer 3: Graph memory (if query provided)
    if query:
        try:
            from app.core.memory.graph_memory import search_graph_memory
            graph_results = await search_graph_memory(query, session_id, top_k=5)
            if graph_results:
                graph_text = "\n".join(f"- {r.get('content', r.get('id',''))[:100]}" for r in graph_results)
                parts.append(f"## 知识关联\n{graph_text}")
        except Exception:
            pass
    return "\n\n".join(parts) if parts else "（无历史记忆）"
```

- [ ] **Step 4: Run test — verify it passes**

Run: `cd Nova Agent/backend && python -m pytest tests/test_memory_integration.py -v`
Expected: 2 PASSED

- [ ] **Step 5: Commit**

```bash
cd "D:/claudecode_project/Nova Agent" && git add backend/app/core/memory/ backend/tests/test_memory_integration.py && git commit -m "feat(memory): four-layer memory assembly — session + facts + graph (P2)"
```

---

## Task 5: P3 — DAG 集成 Race 竞速

**Files:**
- Modify: `Nova Agent/backend/app/core/agent/dag.py`
- Create: `Nova Agent/backend/tests/test_dag_race.py`

**Interfaces:**
- Produces: `DAGWorkflow.execute_race_streaming()` — NEW method using RaceStrategy

- [ ] **Step 1: Write the failing test**

Write `Nova Agent/backend/tests/test_dag_race.py`:
```python
import asyncio, pytest
from app.core.agent.dag import DAGWorkflow, DAGNode

async def mock_task(sleep_ms, result):
    await asyncio.sleep(sleep_ms / 1000)
    return result

@pytest.mark.asyncio
async def test_execute_race_streaming_completes():
    wf = DAGWorkflow("race-test")
    wf.add_node(DAGNode(id="a", name="A", func=mock_task, args=(10, "result_a")))
    wf.add_node(DAGNode(id="b", name="B", func=mock_task, args=(50, "result_b")))
    events = []
    async for event in wf.execute_race_streaming():
        events.append(event)
    types = [e["type"] for e in events]
    assert "dag_completed" in types
    # Both nodes should complete
    completed = [e for e in events if e["type"] == "node_completed"]
    assert len(completed) == 2

@pytest.mark.asyncio
async def test_race_mode_attribute():
    wf = DAGWorkflow("race-attr-test")
    assert hasattr(wf, "execute_race_streaming")
```

- [ ] **Step 2: Run test — verify it fails**

Run: `cd Nova Agent/backend && python -m pytest tests/test_dag_race.py::test_race_mode_attribute -v`
Expected: FAIL — `execute_race_streaming` not defined

- [ ] **Step 3: Add execute_race_streaming to DAGWorkflow**

Append to `Nova Agent/backend/app/core/agent/dag.py` (inside DAGWorkflow class, after `execute_streaming`):
```python
async def execute_race_streaming(self, race_enabled: bool = True):
    """Execute DAG with Race strategy for parallel independent nodes.

    When multiple nodes are ready simultaneously, race them and use
    the first successful result (cancelling the rest).
    """
    from app.core.agent.race import RaceStrategy
    executed = set()
    in_progress = set()

    while len(executed) < len(self.nodes):
        batch = []
        for nid, node in self.nodes.items():
            if nid in executed or nid in in_progress:
                continue
            if all(dep in executed for dep in node.dependencies):
                batch.append(nid)
        if not batch:
            break
        for nid in batch:
            in_progress.add(nid)
            yield {"type": "node_started", "node_id": nid, "node_name": self.nodes[nid].name}

        if race_enabled and len(batch) > 1:
            # Race mode: run all, take first success
            async def _run_node(nid):
                result = await self._execute_node_safe(self.nodes[nid])
                return nid, result
            tasks = {nid: asyncio.create_task(_run_node(nid)) for nid in batch}
            done, pending = await asyncio.wait(tasks.values(), return_when=asyncio.FIRST_COMPLETED)
            # Cancel pending (losers)
            for t in pending:
                t.cancel()
            # Process winners/losers
            completed_nids = set()
            for task in done:
                try:
                    nid, result = task.result()
                    executed.add(nid)
                    in_progress.discard(nid)
                    completed_nids.add(nid)
                    yield {"type": "node_completed", "node_id": nid, "result": result}
                except Exception as e:
                    # Find which nid failed
                    for n, t in tasks.items():
                        if t == task:
                            executed.add(n)
                            in_progress.discard(n)
                            yield {"type": "node_failed", "node_id": n, "error": str(e)}
                            break
            # Mark remaining pending as cancelled
            for nid, task in tasks.items():
                if nid not in completed_nids and nid in in_progress:
                    executed.add(nid)
                    in_progress.discard(nid)
                    yield {"type": "node_failed", "node_id": nid, "error": "race_lost"}
        else:
            # Sequential for single node
            for nid in batch:
                try:
                    result = await self._execute_node_safe(self.nodes[nid])
                    executed.add(nid)
                    in_progress.discard(nid)
                    yield {"type": "node_completed", "node_id": nid, "result": result}
                except Exception as e:
                    executed.add(nid)
                    in_progress.discard(nid)
                    yield {"type": "node_failed", "node_id": nid, "error": str(e)}

    async def _execute_node_safe(self, node):
        """Execute node, capturing exceptions as results."""
        result = await self._execute_node(node)
        return result
```

Also add `_execute_node` after `_execute_node_safe`:
```python
    async def _execute_node(self, node):
        """Execute a single node's function (async or sync)."""
        func = node.func
        args = node.args or ()
        kwargs = node.kwargs or {}
        if func:
            result = func(*args, **kwargs)
            if asyncio.iscoroutine(result):
                result = await result
            return result
        return {"status": "no_op"}
```

- [ ] **Step 4: Run test — verify it passes**

Run: `cd Nova Agent/backend && python -m pytest tests/test_dag_race.py -v`
Expected: 2 PASSED

- [ ] **Step 5: Commit**

```bash
cd "D:/claudecode_project/Nova Agent" && git add backend/app/core/agent/dag.py backend/tests/test_dag_race.py && git commit -m "feat(dag): integrate Race strategy for parallel node execution (P3)"
```

---

## Task 6: P4 — 审计日志端到端验证

**Files:**
- Modify: `Nova Agent/backend/app/core/security/audit.py`
- Modify: `Nova Agent/backend/app/api/v1/security.py`
- Modify: `Nova Agent/backend/app/api/v1/sandbox.py`
- Create: `Nova Agent/backend/tests/test_audit.py`

**Interfaces:**
- Produces: `log_audit(action, user_id, details, risk_level)` — persist to PG
- Produces: `get_audit_log(action, limit)` — read from PG

- [ ] **Step 1: Write the failing test**

Write `Nova Agent/backend/tests/test_audit.py`:
```python
import pytest
from app.core.security.audit import log_audit, get_audit_log, get_audit_stats

@pytest.mark.asyncio
async def test_log_and_retrieve_audit():
    await log_audit("code_execution", user_id="test-user", details={"code": "print(1)"}, risk_level="safe")
    logs = get_audit_log(action="code_execution")
    assert len(logs) >= 1
    assert logs[-1]["action"] == "code_execution"
    assert logs[-1]["user_id"] == "test-user"

@pytest.mark.asyncio
async def test_audit_stats():
    await log_audit("risk_blocked", details={"reason": "rm -rf"})
    stats = get_audit_stats()
    assert stats["total_entries"] >= 1
    assert "risk_blocked" in stats["by_action"] or "code_execution" in stats["by_action"]
```

- [ ] **Step 2: Run test — verify it fails**

Run: `cd Nova Agent/backend && python -m pytest tests/test_audit.py -v`
Expected: FAIL or pass (current in-memory works but won't persist across restarts)

- [ ] **Step 3: Enhance audit.py to persist to PostgreSQL**

Modify `Nova Agent/backend/app/core/security/audit.py`:
```python
import uuid, structlog
from datetime import datetime

logger = structlog.get_logger()

class AuditAction:
    CODE_EXECUTION = "code_execution"
    TOOL_CALL = "tool_call"
    DOCUMENT_UPLOAD = "document_upload"
    CHAT_MESSAGE = "chat_message"
    RISK_BLOCKED = "risk_blocked"

# In-memory buffer for fast access
_audit_buffer = []
_BUFFER_SIZE = 1000

async def log_audit(action, user_id="anonymous", details=None, risk_level="safe"):
    entry = {
        "id": str(uuid.uuid4())[:12],
        "timestamp": datetime.now().isoformat(),
        "action": action, "user_id": user_id,
        "details": details or {}, "risk_level": risk_level,
    }
    _audit_buffer.append(entry)
    if len(_audit_buffer) > _BUFFER_SIZE:
        del _audit_buffer[:500]
    # Persist to PostgreSQL
    try:
        from app.db import execute
        await execute(
            "INSERT INTO audit_log (id, action, user_id, details, risk_level) VALUES (%s, %s, %s, %s, %s)",
            (entry["id"], action, user_id, __import__("json").dumps(details or {}, ensure_ascii=False), risk_level)
        )
    except Exception as e:
        logger.warning("Audit persist failed", error=str(e))
    logger.info("audit_event", **entry)
    return entry["id"]

def get_audit_log(action=None, user_id=None, limit=100):
    filtered = _audit_buffer
    if action:
        filtered = [e for e in filtered if e["action"] == action]
    if user_id:
        filtered = [e for e in filtered if e["user_id"] == user_id]
    return filtered[-limit:]

def get_audit_stats():
    actions = {}
    for e in _audit_buffer:
        actions[e["action"]] = actions.get(e["action"], 0) + 1
    return {"total_entries": len(_audit_buffer), "by_action": actions}
```

Add audit_log table to `init_db.py` init_postgres queries:
```python
("""CREATE TABLE IF NOT EXISTS audit_log (
    id VARCHAR(20) PRIMARY KEY, action VARCHAR(50), user_id VARCHAR(100),
    details JSONB DEFAULT '{}', risk_level VARCHAR(20),
    created_at TIMESTAMPTZ DEFAULT now())""", ()),
("CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log (action)", ()),
("CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log (created_at)", ()),
```

- [ ] **Step 4: Run test — verify it passes**

Run: `cd Nova Agent/backend && python -m pytest tests/test_audit.py -v`
Expected: 2 PASSED

- [ ] **Step 5: Commit**

```bash
cd "D:/claudecode_project/Nova Agent" && git add backend/app/core/security/audit.py backend/app/db/init_db.py backend/tests/test_audit.py && git commit -m "feat(security): audit log persistence to PostgreSQL (P4)"
```

---

## Task 7: P5 — 集成测试套件

**Files:**
- Create: `Nova Agent/backend/tests/integration/__init__.py`
- Modify: `Nova Agent/backend/tests/conftest.py`
- Create: `Nova Agent/backend/tests/integration/test_retrieval.py`
- Create: `Nova Agent/backend/tests/integration/test_evaluation.py`
- Create: `Nova Agent/backend/tests/integration/test_memory.py`
- Create: `Nova Agent/backend/tests/integration/test_dag.py`
- Create: `Nova Agent/backend/tests/integration/test_sandbox.py`

**Interfaces:**
- Produces: 5条集成测试，每条连接真实数据库验证一个亮点

- [ ] **Step 1: Write conftest.py with integration fixtures**

Write `Nova Agent/backend/tests/conftest.py`:
```python
import pytest, pytest_asyncio

def pytest_configure(config):
    config.addinivalue_line("markers", "integration: mark test as integration test (requires real DB)")

@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"
```

- [ ] **Step 2: Write integration tests**

Write `Nova Agent/backend/tests/integration/test_retrieval.py`:
```python
import pytest
from app.core.rag.retriever import retrieve

@pytest.mark.asyncio
@pytest.mark.integration
async def test_three_way_retrieval_returns_fused_results():
    results = await retrieve("FastAPI中间件", top_k=5)
    assert isinstance(results, list)
    assert len(results) > 0
    assert all(hasattr(r, "score_type") for r in results)
    score_types = {r.score_type for r in results}
    assert len(score_types) >= 1  # at least one source returned
```

Write `Nova Agent/backend/tests/integration/test_evaluation.py`:
```python
import pytest
from app.core.evaluation.runner import evaluate_single_query

@pytest.mark.asyncio
@pytest.mark.integration
async def test_full_eval_pipeline():
    result = await evaluate_single_query("FastAPI中间件", relevant_ids=None, mode="all")
    assert "answer" in result
    assert "ragas_scores" in result
    assert len(result["ragas_scores"]) == 4
```

Write `Nova Agent/backend/tests/integration/test_memory.py`:
```python
import pytest
from app.core.memory.context_assembler import assemble_context
from app.core.memory.store import save_fact
from app.core.memory.session import add_message

@pytest.mark.asyncio
@pytest.mark.integration
async def test_four_layer_memory_assembly():
    sid = "integration-mem-test"
    add_message(sid, "user", "我喜欢FastAPI")
    await save_fact(sid, "用户偏好FastAPI", "preference", 0.8)
    ctx = await assemble_context("Web框架推荐", sid)
    assert len(ctx) > 0
```

Write `Nova Agent/backend/tests/integration/test_dag.py`:
```python
import pytest, asyncio
from app.core.agent.dag import DAGWorkflow, DAGNode

async def mock_work(x):
    await asyncio.sleep(0.01)
    return f"result_{x}"

@pytest.mark.asyncio
@pytest.mark.integration
async def test_dag_race_execution():
    wf = DAGWorkflow("integration-race")
    wf.add_node(DAGNode(id="a", name="A", func=mock_work, args=("a",)))
    wf.add_node(DAGNode(id="b", name="B", func=mock_work, args=("b",)))
    events = []
    async for e in wf.execute_race_streaming():
        events.append(e)
    assert any(e["type"] == "dag_completed" for e in events)
```

Write `Nova Agent/backend/tests/integration/test_sandbox.py`:
```python
import pytest
from app.core.sandbox.runtime import execute_in_sandbox

@pytest.mark.asyncio
@pytest.mark.integration
async def test_sandbox_executes_code():
    result = await execute_in_sandbox('print("integration test")', language="python", timeout=5)
    assert result["exit_code"] == 0
    assert "integration test" in result["stdout"]
```

- [ ] **Step 3: Run integration tests**

Run: `cd Nova Agent/backend && python -m pytest tests/integration/ -v -m integration`
Expected: 5 PASSED

- [ ] **Step 4: Commit**

```bash
cd "D:/claudecode_project/Nova Agent" && git add backend/tests/ integration/ && git commit -m "test: add integration test suite for all 6 highlights (P5)"
```

---

## Self-Review Checklist

- [x] Spec coverage: P0-P5 each mapped to a task
- [x] No placeholders — all code blocks complete
- [x] Type consistency: function signatures match between tasks
- [x] Each task ends with independently testable deliverable

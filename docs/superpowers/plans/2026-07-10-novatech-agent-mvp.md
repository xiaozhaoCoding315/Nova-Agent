# NovaTech Agent MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the NovaTech Agent MVP — a cyberpunk-styled AI technical assistant with three-way retrieval (Qdrant + PostgreSQL + Neo4j), AI model fallback chain (Longcat → DeepSeek → DashScope), and SSE-streamed chat.

**Architecture:** Full three-layer setup: React+TypeScript frontend (Vite + TailwindCSS + Three.js + Framer Motion) → FastAPI backend → databases + LLM APIs. Backend orchestrates parallel async retrieval from Qdrant, PostgreSQL FTS, and Neo4j, fuses with RRF, and streams LLM responses via Server-Sent Events.

**Tech Stack:** React 18, TypeScript, Vite 5, TailwindCSS 3, Three.js, Framer Motion, Zustand, Python 3.12+, FastAPI, Qdrant, PostgreSQL, Neo4j, OpenAI SDK (compatible interface)

## Global Constraints

- Backend host for databases: `192.168.150.128`
- Qdrant port: `6333`, PostgreSQL port: `5432`, Neo4j port: `7687`
- AI model fallback chain priority: Longcat2.0 → DeepSeek → DashScope
- Environment variables `DEEPSEEK_API_KEY` and `DASHSCOPE_API_KEY` already configured in user's system env
- Frontend dev server: `http://localhost:5173`
- All Python async code uses `async/await` pattern
- All SSE events use `{"type": "..."}` JSON format
- TDD: write failing test first, then implement, then commit
- Commit after each task

---

## Task 1: Project Skeleton & Configuration

**Files:**
- Create: `Nova Agent/.gitignore`
- Create: `Nova Agent/docker-compose.yml`
- Create: `Nova Agent/backend/.env.example`
- Create: `Nova Agent/backend/requirements.txt`
- Create: `Nova Agent/backend/Dockerfile`
- Create: `Nova Agent/frontend/.gitignore`
- Create: `Nova Agent/frontend/package.json`
- Create: `Nova Agent/frontend/vite.config.ts`
- Create: `Nova Agent/frontend/tsconfig.json`
- Create: `Nova Agent/frontend/tsconfig.node.json`
- Create: `Nova Agent/frontend/index.html`
- Create: `Nova Agent/frontend/tailwind.config.ts`
- Create: `Nova Agent/frontend/postcss.config.js`

**Interfaces:**
- Produces: `backend/.env.example` — all connection variables
- Produces: `docker-compose.yml` — reference stack

- [ ] **Step 1: Create root .gitignore and docker-compose.yml**

Write `Nova Agent/.gitignore`:
```gitignore
__pycache__/
*.py[cod]
*.egg-info/
.venv/
venv/
.env
node_modules/
dist/
.vscode/
.idea/
.DS_Store
Thumbs.db
backend/logs/
frontend/dist/
```

Write `Nova Agent/docker-compose.yml`:
```yaml
# Reference only — user hosts services at 192.168.150.128
version: "3.9"
services:
  qdrant:
    image: qdrant/qdrant:latest
    ports: ["6333:6333"]
    volumes: [qdrant_data:/qdrant/storage]
  postgres:
    image: pgvector/pgvector:pg16
    ports: ["5432:5432"]
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-novatech}
      POSTGRES_DB: novatech
    volumes: [pg_data:/var/lib/postgresql/data]
  neo4j:
    image: neo4j:5-community
    ports: ["7474:7474", "7687:7687"]
    environment:
      NEO4J_AUTH: neo4j/${NEO4J_PASSWORD:-novatech123}
    volumes: [neo4j_data:/data]
volumes:
  qdrant_data:
  pg_data:
  neo4j_data:
```

- [ ] **Step 2: Create backend config files**

Write `Nova Agent/backend/requirements.txt`:
```txt
fastapi==0.115.0
uvicorn[standard]==0.30.6
pydantic-settings==2.5.2
qdrant-client==1.11.3
psycopg[binary]==3.2.3
neo4j==5.24.0
openai==1.51.2
greenlet==3.1.1
structlog==24.4.0
python-multipart==0.0.12
pytest==8.3.3
pytest-asyncio==0.24.0
```

Write `Nova Agent/backend/.env.example`:
```env
LLM_MODEL_PRIORITY=longcat,deepseek,dashscope
LONGCAT_API_KEY=your_key
LONGCAT_BASE_URL=https://api.longcat.chat/openai/v1
LONGCAT_MODEL=LongCat-2.0
DEEPSEEK_API_KEY=your_key
DASHSCOPE_API_KEY=your_key
QDRANT_HOST=192.168.150.128
QDRANT_PORT=6333
POSTGRES_HOST=192.168.150.128
POSTGRES_PORT=5432
POSTGRES_USER=postgres
POSTGRES_PASSWORD=novatech
POSTGRES_DB=novatech
NEO4J_HOST=192.168.150.128
NEO4J_PORT=7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=novatech123
EMBEDDING_PROVIDER=dashscope
EMBEDDING_MODEL=text-embedding-v3
DEBUG=true
LOG_LEVEL=INFO
SECRET_KEY=change-me
CORS_ORIGINS=http://localhost:5173
```

Write `Nova Agent/backend/Dockerfile`:
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 3: Create frontend config files**

Write `Nova Agent/frontend/package.json`:
```json
{
  "name": "novatech-frontend",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "@react-three/fiber": "^8.17.0",
    "@react-three/drei": "^9.114.0",
    "axios": "^1.7.7",
    "framer-motion": "^11.11.0",
    "lucide-react": "^0.453.0",
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "three": "^0.169.0",
    "zustand": "^5.0.0"
  },
  "devDependencies": {
    "@types/react": "^18.3.11",
    "@types/react-dom": "^18.3.1",
    "@types/three": "^0.169.0",
    "@vitejs/plugin-react": "^4.3.2",
    "autoprefixer": "^10.4.20",
    "postcss": "^8.4.47",
    "tailwindcss": "^3.4.14",
    "typescript": "^5.6.3",
    "vite": "^5.4.9"
  }
}
```

Write `Nova Agent/frontend/vite.config.ts`:
```ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { '/api': { target: 'http://localhost:8000', changeOrigin: true } },
  },
})
```

Write `Nova Agent/frontend/tsconfig.json`:
```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "baseUrl": ".",
    "paths": { "@/*": ["src/*"] }
  },
  "include": ["src"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

Write `Nova Agent/frontend/tsconfig.node.json`:
```json
{
  "compilerOptions": {
    "composite": true,
    "skipLibCheck": true,
    "module": "ESNext",
    "moduleResolution": "bundler",
    "allowSyntheticDefaultImports": true,
    "strict": true
  },
  "include": ["vite.config.ts"]
}
```

Write `Nova Agent/frontend/tailwind.config.ts`:
```ts
import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        cyber: {
          bg: '#0a0a0f',
          surface: '#12121a',
          border: '#1e1e2e',
          cyan: '#00f0f0',
          pink: '#ff006e',
          purple: '#8b5cf6',
          text: '#e0e0e0',
          textDim: '#9ca3af',
        },
      },
      animation: {
        'pulse-glow': 'pulse-glow 2s ease-in-out infinite',
        'float': 'float 6s ease-in-out infinite',
      },
      keyframes: {
        'pulse-glow': {
          '0%, 100%': { boxShadow: '0 0 5px #00f0f0, 0 0 20px #00f0f055' },
          '50%': { boxShadow: '0 0 20px #00f0f0, 0 0 60px #00f0f088' },
        },
        'float': {
          '0%, 100%': { transform: 'translateY(0px)' },
          '50%': { transform: 'translateY(-10px)' },
        },
      },
    },
  },
  plugins: [],
} satisfies Config
```

Write `Nova Agent/frontend/postcss.config.js`:
```js
export default { plugins: { tailwindcss: {}, autoprefixer: {} } }
```

Write `Nova Agent/frontend/index.html`:
```html
<!DOCTYPE html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>NovaTech Agent</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

Write `Nova Agent/frontend/.gitignore`:
```gitignore
node_modules/
dist/
*.local
```

- [ ] **Step 4: Commit**

Run:
```bash
cd "D:/claudecode_project/Nova Agent" && git add . && git commit -m "chore: initialize project skeleton and configuration"
```

---

## Task 2: Backend — Config, Main App, Health Check

**Files:**
- Create: `Nova Agent/backend/app/__init__.py`
- Create: `Nova Agent/backend/app/config.py`
- Create: `Nova Agent/backend/app/main.py`
- Create: `Nova Agent/backend/app/api/__init__.py`
- Create: `Nova Agent/backend/app/api/v1/__init__.py`
- Create: `Nova Agent/backend/app/api/v1/router.py`
- Create: `Nova Agent/backend/app/api/v1/health.py`
- Create: `Nova Agent/backend/tests/__init__.py`
- Create: `Nova Agent/backend/tests/test_config.py`
- Create: `Nova Agent/backend/tests/test_health.py`

**Interfaces:**
- Produces: `config.settings` — Settings instance with all env vars
- Produces: `app.main.app` — FastAPI application
- Produces: `GET /api/v1/health` → `{"status": "ok", "version": "0.1.0"}`

- [ ] **Step 1: Create package __init__ files**

Write the following as empty files:
- `Nova Agent/backend/app/__init__.py`
- `Nova Agent/backend/app/api/__init__.py`
- `Nova Agent/backend/app/api/v1/__init__.py`
- `Nova Agent/backend/tests/__init__.py`

- [ ] **Step 2: Write the failing config test**

Write `Nova Agent/backend/tests/test_config.py`:
```python
from app.config import Settings


def test_settings_defaults():
    s = Settings()
    assert s.postgres_host == "192.168.150.128"
    assert s.qdrant_port == 6333
    assert s.neo4j_port == 7687


def test_llm_priority_parsing():
    s = Settings(llm_model_priority="longcat,deepseek")
    assert s.llm_priority_list == ["longcat", "deepseek"]


def test_connection_urls():
    s = Settings()
    assert s.qdrant_url == "http://192.168.150.128:6333"
    assert "postgresql://" in s.postgres_dsn
    assert s.neo4j_uri == "bolt://192.168.150.128:7687"
```

- [ ] **Step 3: Run test — verify it fails**

Run: `cd Nova Agent/backend && python -m pytest tests/test_config.py -v`
Expected: ImportError/FAIL

- [ ] **Step 4: Write config module**

Write `Nova Agent/backend/app/config.py`:
```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_model_priority: str = "longcat,deepseek,dashscope"
    longcat_api_key: str = ""
    longcat_base_url: str = "https://api.longcat.chat/openai/v1"
    longcat_model: str = "LongCat-2.0"
    deepseek_api_key: str = ""
    dashscope_api_key: str = ""

    qdrant_host: str = "192.168.150.128"
    qdrant_port: int = 6333

    postgres_host: str = "192.168.150.128"
    postgres_port: int = 5432
    postgres_user: str = "postgres"
    postgres_password: str = "novatech"
    postgres_db: str = "novatech"

    neo4j_host: str = "192.168.150.128"
    neo4j_port: int = 7687
    neo4j_user: str = "neo4j"
    neo4j_password: str = "novatech123"

    embedding_provider: str = "dashscope"
    embedding_model: str = "text-embedding-v3"

    debug: bool = True
    log_level: str = "INFO"
    secret_key: str = "change-me"
    cors_origins: str = "http://localhost:5173"

    @property
    def llm_priority_list(self) -> list[str]:
        return [p.strip() for p in self.llm_model_priority.split(",") if p.strip()]

    @property
    def qdrant_url(self) -> str:
        return f"http://{self.qdrant_host}:{self.qdrant_port}"

    @property
    def neo4j_uri(self) -> str:
        return f"bolt://{self.neo4j_host}:{self.neo4j_port}"

    @property
    def postgres_dsn(self) -> str:
        return (f"postgresql://{self.postgres_user}:{self.postgres_password}"
                f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}")

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
```

- [ ] **Step 5: Run test — verify it passes**

Run: `cd Nova Agent/backend && python -m pytest tests/test_config.py -v`
Expected: 3 PASSED

- [ ] **Step 6: Write the failing health check test**

Write `Nova Agent/backend/tests/test_health.py`:
```python
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health():
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "version": "0.1.0"}
```

- [ ] **Step 7: Run test — verify it fails**

Run: `cd Nova Agent/backend && python -m pytest tests/test_health.py -v`
Expected: FAIL — app not defined

- [ ] **Step 8: Write health route and main app**

Write `Nova Agent/backend/app/api/v1/health.py`:
```python
from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health_check():
    return {"status": "ok", "version": "0.1.0"}
```

Write `Nova Agent/backend/app/api/v1/router.py`:
```python
from fastapi import APIRouter
from app.api.v1 import health

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
```

Write `Nova Agent/backend/app/main.py`:
```python
import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.api.v1.router import api_router

logger = structlog.get_logger()

app = FastAPI(title="NovaTech Agent", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")


@app.on_event("startup")
async def on_startup():
    logger.info("NovaTech starting", version="0.1.0")


@app.on_event("shutdown")
async def on_shutdown():
    logger.info("NovaTech shutting down")
```

- [ ] **Step 9: Run all tests — verify they pass**

Run: `cd Nova Agent/backend && python -m pytest tests/ -v`
Expected: All PASSED

- [ ] **Step 10: Commit**

Run:
```bash
cd "D:/claudecode_project/Nova Agent" && git add backend/ && git commit -m "feat(backend): add config, health check, FastAPI skeleton"
```

---

## Task 3: Backend — RRF Fusion

**Files:**
- Create: `Nova Agent/backend/app/models/__init__.py`
- Create: `Nova Agent/backend/app/models/domain.py`
- Create: `Nova Agent/backend/app/core/__init__.py`
- Create: `Nova Agent/backend/app/core/rag/__init__.py`
- Create: `Nova Agent/backend/app/core/rag/rrf.py`
- Create: `Nova Agent/backend/tests/test_rrf.py`

**Interfaces:**
- Produces: `RetrievedChunk(id, content, source, score_type, score, metadata)`
- Produces: `rrf_fuse(lists, k=60, top_n=5) -> list[RetrievedChunk]`

- [ ] **Step 1: Write failing RRF test**

Write `Nova Agent/backend/tests/test_rrf.py`:
```python
from app.core.rag.rrf import rrf_fuse
from app.models.domain import RetrievedChunk


def test_single_list_preserves_order():
    chunks = [
        RetrievedChunk(id="1", content="A", source="d", score_type="dense"),
        RetrievedChunk(id="2", content="B", source="d", score_type="dense"),
        RetrievedChunk(id="3", content="C", source="d", score_type="dense"),
    ]
    result = rrf_fuse([chunks], top_n=2)
    assert [c.id for c in result] == ["1", "2"]


def test_multi_list_cross_boost():
    l1 = [
        RetrievedChunk(id="1", content="A", source="d", score_type="dense"),
        RetrievedChunk(id="2", content="B", source="d", score_type="dense"),
    ]
    l2 = [
        RetrievedChunk(id="2", content="B", source="d", score_type="keyword"),
        RetrievedChunk(id="3", content="C", source="d", score_type="keyword"),
    ]
    result = rrf_fuse([l1, l2], top_n=3)
    assert result[0].id == "2"  # appears in both → boosted
    assert len(result) == 3


def test_empty_input():
    assert rrf_fuse([], top_n=5) == []
    assert rrf_fuse([[]], top_n=5) == []


def test_top_n_limits_output():
    l1 = [RetrievedChunk(id=str(i), content=str(i), source="d", score_type="dense") for i in range(20)]
    result = rrf_fuse([l1], top_n=5)
    assert len(result) == 5
```

- [ ] **Step 2: Run test — verify it fails**

Run: `cd Nova Agent/backend && python -m pytest tests/test_rrf.py -v`
Expected: ImportError

- [ ] **Step 3: Write domain models**

Create `Nova Agent/backend/app/models/__init__.py` (empty).

Write `Nova Agent/backend/app/models/domain.py`:
```python
from pydantic import BaseModel


class RetrievedChunk(BaseModel):
    id: str
    content: str
    source: str
    score_type: str  # "dense" | "keyword" | "graph"
    score: float = 0.0
    metadata: dict = {}
```

- [ ] **Step 4: Write RRF implementation**

Create `Nova Agent/backend/app/core/__init__.py` (empty).
Create `Nova Agent/backend/app/core/rag/__init__.py` (empty).

Write `Nova Agent/backend/app/core/rag/rrf.py`:
```python
from app.models.domain import RetrievedChunk


def rrf_fuse(
    lists: list[list[RetrievedChunk]],
    k: int = 60,
    top_n: int = 5,
) -> list[RetrievedChunk]:
    """Reciprocal Rank Fusion merges multiple ranked result lists."""
    scores: dict[str, float] = {}
    chunk_map: dict[str, RetrievedChunk] = {}

    for ranked_list in lists:
        for rank, chunk in enumerate(ranked_list):
            if chunk.id not in scores:
                scores[chunk.id] = 0.0
                chunk_map[chunk.id] = chunk
            scores[chunk.id] += 1.0 / (k + rank + 1)

    sorted_ids = sorted(scores, key=lambda x: scores[x], reverse=True)
    result = []
    for cid in sorted_ids[:top_n]:
        chunk = chunk_map[cid]
        chunk.score = scores[cid]
        result.append(chunk)
    return result
```

- [ ] **Step 5: Run test — verify it passes**

Run: `cd Nova Agent/backend && python -m pytest tests/test_rrf.py -v`
Expected: 4 PASSED

- [ ] **Step 6: Commit**

Run:
```bash
cd "D:/claudecode_project/Nova Agent" && git add backend/app/models/ backend/app/core/ backend/tests/test_rrf.py && git commit -m "feat(backend): add RRF fusion algorithm for multi-list retrieval ranking"
```

---

## Task 4: Backend — Embedding Module

**Files:**
- Create: `Nova Agent/backend/app/core/embedding/__init__.py`
- Create: `Nova Agent/backend/app/core/embedding/embedder.py`
- Create: `Nova Agent/backend/tests/test_embedder.py`

**Interfaces:**
- Produces: `Embedder.embed(texts: list[str]) -> list[list[float]]`
- Produces: `get_embedder() -> Embedder` (factory from settings)

- [ ] **Step 1: Write failing embedder test**

Write `Nova Agent/backend/tests/test_embedder.py`:
```python
import pytest
from app.core.embedding.embedder import Embedder, get_embedder


class DummyEmbedder(Embedder):
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3] for _ in texts]


def test_embedder_returns_correct_dimensions():
    e = DummyEmbedder()
    vectors = e.embed(["hello", "world"])
    assert len(vectors) == 2
    assert len(vectors[0]) == 3


def test_factory_returns_embedder():
    # Will fail until factory is implemented
    from app.core.embedder import get_embedder
    e = get_embedder()
    assert e is not None
```

- [ ] **Step 2: Run test — verify it fails**

Run: `cd Nova Agent/backend && python -m pytest tests/test_embedder.py::test_factory_returns_embedder -v`
Expected: ImportError

- [ ] **Step 3: Write embedder module**

Write `Nova Agent/backend/app/core/embedding/__init__.py`: (empty)

Write `Nova Agent/backend/app/core/embedding/embedder.py`:
```python
from abc import ABC, abstractmethod
from openai import AsyncOpenAI
from app.config import settings


class Embedder(ABC):
    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        ...


class OpenAIEmbedder(Embedder):
    def __init__(self):
        self.client = AsyncOpenAI(
            api_key=settings.dashscope_api_key,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        self.model = settings.embedding_model

    async def embed(self, texts: list[str]) -> list[list[float]]:
        resp = await self.client.embeddings.create(model=self.model, input=texts)
        return [d.embedding for d in resp.data]


def get_embedder() -> Embedder:
    return OpenAIEmbedder()
```

Run tests:
```bash
cd Nova Agent/backend && python -m pytest tests/test_embedder.py -v
```
Expected: 2 PASSED

- [ ] **Step 4: Commit**

```bash
cd "D:/claudecode_project/Nova Agent" && git add backend/app/core/embedding/ backend/tests/test_embedder.py && git commit -m "feat(backend): add embedding module with DashScope/OpenAI-compatible provider"
```

---

## Task 5: Backend — Three Retrievers (Dense, Keyword, Graph)

**Files:**
- Create: `Nova Agent/backend/app/core/rag/dense.py`
- Create: `Nova Agent/backend/app/core/rag/keyword.py`
- Create: `Nova Agent/backend/app/core/rag/graph.py`
- Create: `Nova Agent/backend/app/core/rag/retriever.py`
- Create: `Nova Agent/backend/tests/test_retrievers.py`

**Interfaces:**
- Produces: `dense_search(query, top_k=10) -> list[RetrievedChunk]`
- Produces: `keyword_search(query, top_k=10) -> list[RetrievedChunk]`
- Produces: `graph_search(query, top_k=10) -> list[RetrievedChunk]`
- Produces: `retrieve(query, top_k=10) -> list[RetrievedChunk]` (parallel + RRF)

- [ ] **Step 1: Write failing retriever integration test**

Write `Nova Agent/backend/tests/test_retriever.py`:
```python
import pytest
from unittest.mock import AsyncMock, patch
from app.core.rag.retriever import retrieve


@pytest.mark.asyncio
async def test_retrieve_merges_all_three_sources():
    dense_results = [RetrievedChunk(id="d1", content="fastapi", source="doc.md", score_type="dense")]
    keyword_results = [RetrievedChunk(id="k1", content="中间件", source="doc2.md", score_type="keyword")]
    graph_results = [RetrievedChunk(id="g1", content="依赖注入", source="doc3.md", score_type="graph")]

    with patch("app.core.rag.retriever.dense_search", new=AsyncMock(return_value=dense_results)), \
         patch("app.core.rag.retriever.keyword_search", new=AsyncMock(return_value=keyword_results)), \
         patch("app.core.rag.retriever.graph_search", new=AsyncMock(return_value=graph_results)):
        result = await retrieve("FastAPI中间件", top_k=5)
    ids = {c.id for c in result}
    assert "d1" in ids and "k1" in ids and "g1" in ids


from app.models.domain import RetrievedChunk
```

- [ ] **Step 2: Write retriever modules**

Write `Nova Agent/backend/app/core/rag/dense.py`:
```python
from qdrant_client import QdrantClient
from app.config import settings
from app.models.domain import RetrievedChunk
from app.core.embedding.embedder import get_embedder

_client = QdrantClient(url=settings.qdrant_url)
_embedder = get_embedder()


async def dense_search(query: str, top_k: int = 10) -> list[RetrievedChunk]:
    vector = (await _embedder.embed([query]))[0]
    results = _client.search(
        collection_name="novatech_docs",
        query_vector=vector,
        limit=top_k,
    )
    return [
        RetrievedChunk(
            id=str(r.id),
            content=r.payload.get("content", ""),
            source=r.payload.get("source", ""),
            score_type="dense",
            score=r.score or 0.0,
            metadata=r.payload,
        )
        for r in results
    ]
```

Write `Nova Agent/backend/app/core/rag/keyword.py`:
```python
import psycopg
from app.config import settings
from app.models.domain import RetrievedChunk


async def keyword_search(query: str, top_k: int = 10) -> list[RetrievedChunk]:
    async with await psycopg.AsyncConnection.connect(settings.postgres_dsn) as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                id, content, source,
                ts_rank(search_vector, plainto_tsquery('chinese', %s)) AS rank
                FROM documents
                WHERE search_vector @@ plainto_tsquery('chinese', %s)
                ORDER BY rank DESC
                LIMIT %s
                """,
                (query, query, top_k),
            )
            rows = await cur.fetchall()
    return [
        RetrievedChunk(
            id=str(row[0]),
            content=row[1],
            source=row[2],
            score_type="keyword",
            score=float(row[3]) if row[3] else 0.0,
        )
        for row in rows
    ]
```

Write `Nova Agent/backend/app/core/rag/graph.py`:
```python
from neo4j import AsyncGraphDatabase
from app.config import settings
from app.models.domain import RetrievedChunk

_driver = AsyncGraphDatabase.driver(settings.neo4j_uri,
    auth=(settings.neo4j_user, settings.neo4j_password))


async def graph_search(query: str, top_k: int = 10) -> list[RetrievedChunk]:
    async with _driver.session() as session:
        result = await session.run(
            """
            CALL db.index.fulltext.queryNodes('entityIndex', $query)
            YIELD node, score
            RETURN node.name AS name, node.content AS content,
                   node.source AS source, score
            ORDER BY score DESC LIMIT $top_k
            """,
            query=query, top_k=top_k,
        )
        records = await result.data()
    return [
        RetrievedChunk(
            id=r["name"],
            content=r.get("content", r["name"]),
            source=r.get("source", "graph"),
            score_type="graph",
            score=float(r["score"]),
        )
        for r in records
    ]
```

Write `Nova Agent/backend/app/core/rag/retriever.py`:
```python
import asyncio
from app.models.domain import RetrievedChunk
from app.core.rag.dense import dense_search
from app.core.rag.keyword import keyword_search
from app.core.rag.graph import graph_search
from app.core.rag.rrf import rrf_fuse


async def retrieve(query: str, top_k: int = 10) -> list[RetrievedChunk]:
    """Parallel three-way retrieval with RRF fusion."""
    dense_task = asyncio.create_task(dense_search(query, top_k))
    keyword_task = asyncio.create_task(keyword_search(query, top_k))
    graph_task = asyncio.create_task(graph_search(query, top_k))

    results = await asyncio.gather(
        dense_task, keyword_task, graph_task,
        return_exceptions=True,
    )

    valid_lists: list[list[RetrievedChunk]] = []
    for r in results:
        if isinstance(r, Exception):
            continue  # skip failed sources
        valid_lists.append(r)

    return rrf_fuse(valid_lists, top_n=min(5, top_k))
```

- [ ] **Step 3: Run tests**

```bash
cd Nova Agent/backend && python -m pytest tests/test_retriever.py -v
```

- [ ] **Step 4: Commit**

```bash
cd "D:/claudecode_project/Nova Agent" && git add backend/app/core/rag/ backend/tests/test_retriever.py && git commit -m "feat(backend): add three-way parallel retrieval (dense/keyword/graph) with RRF fusion"
```

---

## Task 6: Backend — LLM Fallback Chain

**Files:**
- Create: `Nova Agent/backend/app/core/llm/__init__.py`
- Create: `Nova Agent/backend/app/core/llm/base.py`
- Create: `Nova Agent/backend/app/core/llm/fallback.py`
- Create: `Nova Agent/backend/app/core/llm/factory.py`
- Create: `Nova Agent/backend/app/models/schemas.py`
- Create: `Nova Agent/backend/tests/test_llm_fallback.py`

**Interfaces:**
- Produces: `LLMProvider.astream(messages) -> AsyncIterator[str]` (streaming tokens)
- Produces: `get_llm() -> LLMProvider` (factory with fallback chain)

- [ ] **Step 1: Write failing LLM test**

Write `Nova Agent/backend/tests/test_llm_fallback.py`:
```python
import pytest
from unittest.mock import AsyncMock, patch
from app.core.llm.fallback import FallbackLLM
from app.core.llm.base import LLMProvider


class FakeLLM(LLMProvider):
    def __init__(self, name, should_fail=False):
        self._name = name
        self._should_fail = should_fail

    async def astream(self, messages):
        if self._should_fail:
            raise RuntimeError(f"{self._name} down")
        yield f"response from {self._name}"


@pytest.mark.asyncio
async def test_fallback_tries_next_on_failure():
    primary = FakeLLM("longcat", should_fail=True)
    secondary = FakeLLM("deepseek")
    fb = FallbackLLM([primary, secondary])

    tokens = []
    async for token in fb.astream([{"role": "user", "content": "hi"}]):
        tokens.append(token)
    assert "response from deepseek" in tokens


@pytest.mark.asyncio
async def test_fallback_uses_first_successful():
    primary = FakeLLM("longcat")
    secondary = FakeLLM("deepseek")
    fb = FallbackLLM([primary, secondary])

    tokens = []
    async for token in fb.astream([{"role": "user", "content": "hi"}]):
        tokens.append(token)
    assert "response from longcat" in tokens
```

- [ ] **Step 2: Write LLM modules**

Write `Nova Agent/backend/app/core/llm/__init__.py`: (empty)

Write `Nova Agent/backend/app/core/llm/base.py`:
```python
from abc import ABC, abstractmethod


class LLMProvider(ABC):
    @abstractmethod
    async def astream(self, messages: list[dict]) -> any:
        """Yield string tokens."""
        ...
```

Write `Nova Agent/backend/app/core/llm/fallback.py`:
```python
import structlog
from app.core.llm.base import LLMProvider

logger = structlog.get_logger()


class FallbackLLM(LLMProvider):
    def __init__(self, providers: list[LLMProvider]):
        self.providers = providers

    async def astream(self, messages: list[dict]):
        for provider in self.providers:
            try:
                async for token in provider.astream(messages):
                    yield token
                return  # success — stop chain
            except Exception as e:
                logger.warning("LLM provider failed, trying next",
                             provider=type(provider).__name__, error=str(e))
                continue
        raise RuntimeError("All LLM providers failed")
```

Write `Nova Agent/backend/app/core/llm/factory.py`:
```python
from openai import AsyncOpenAI
from app.config import settings
from app.core.llm.base import LLMProvider


class OpenAICompatibleLLM(LLMProvider):
    def __init__(self, api_key: str, base_url: str, model: str):
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.model = model

    async def astream(self, messages: list[dict]):
        stream = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            stream=True,
        )
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content


def get_llm() -> LLMProvider:
    from app.core.llm.fallback import FallbackLLM
    from app.models.schemas import ChatResponse

    providers = []
    priority = settings.llm_priority_list

    for name in priority:
        name = name.lower()
        if name == "longcat" and settings.longcat_api_key:
            providers.append(OpenAICompatibleLLM(
                settings.longcat_api_key, settings.longcat_base_url, settings.longcat_model))
        elif name == "deepseek" and settings.deepseek_api_key:
            providers.append(OpenAICompatibleLLM(
                settings.deepseek_api_key,
                "https://api.deepseek.com/v1",
                "deepseek-chat"))
        elif name == "dashscope" and settings.dashscope_api_key:
            providers.append(OpenAICompatibleLLM(
                settings.dashscope_api_key,
                "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "qwen-turbo"))

    if not providers:
        raise RuntimeError("No LLM providers configured")
    return FallbackLLM(providers)
```

Write `Nova Agent/backend/app/models/schemas.py`:
```python
from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str
    session_id: str = ""


class ChatResponse(BaseModel):
    session_id: str
    tokens: int
    retrieval_time_ms: float


class RetrievedItem(BaseModel):
    id: str
    content: str
    source: str
    score_type: str
    score: float


class SSERetrieval(BaseModel):
    type: str = "retrieval"
    data: list[RetrievedItem]


class SSEToken(BaseModel):
    type: str = "token"
    content: str


class SSEResponseInfo(BaseModel):
    type: str = "done"
    session_id: str
    retrieval_time_ms: float
    tokens: int
```

Run: `cd Nova Agent/backend && python -m pytest tests/test_llm_fallback.py -v`
Expected: 2 PASSED

- [ ] **Step 3: Commit**

```bash
cd "D:/claudecode_project/Nova Agent" && git add backend/app/core/llm/ backend/app/models/schemas.py backend/tests/test_llm_fallback.py && git commit -m "feat(backend): add LLM fallback chain (longcat->deepseek->dashscope)"
```

---

## Task 7: Backend — Chat SSE Route

**Files:**
- Create: `Nova Agent/backend/app/api/v1/chat.py`
- Modify: `Nova Agent/backend/app/api/v1/router.py`
- Create: `Nova Agent/backend/tests/test_chat_api.py`

**Interfaces:**
- Produces: `POST /api/v1/chat/message` — SSE stream endpoint

- [ ] **Step 1: Write failing chat test**

Write `Nova Agent/backend/tests/test_chat_api.py`:
```python
import json
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch
from app.main import app


def test_chat_returns_sse_stream():
    mock_chunks = [
        {"id": "1", "content": "FastAPI中间件", "source": "doc.md",
         "score_type": "dense", "score": 0.9, "metadata": {}},
    ]
    mock_token = "FastAPI中间件通过@app.middleware装饰器实现"

    async def fake_retrieve(q, top_k=5):
        return []

    async def fake_stream(messages):
        yield mock_token

    with patch("app.api.v1.chat.retrieve", new=fake_retrieve), \
         patch("app.api.v1.chat.get_llm") as mock_llm:
        mock_llm.return_value.astream = fake_stream
        with TestClient(app).stream(
            "POST", "/api/v1/chat/message",
            json={"message": "FastAPI中间件"},
        ) as resp:
            assert resp.status_code == 200
            body = b""
            for chunk in resp.iter_bytes():
                body += chunk
            assert b"FastAPI中间件" in body.encode() if isinstance(body, str) else b"FastAPI" in body
```

- [ ] **Step 2: Write chat route**

Write `Nova Agent/backend/app/api/v1/chat.py`:
```python
import json
import time
import uuid
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from app.config import settings
from app.models.schemas import ChatRequest, RetrievedItem, SSEToken, SSEResponseInfo
from app.core.rag.retriever import retrieve
from app.core.llm.factory import get_llm

router = APIRouter()


async def event_stream(question: str, session_id: str):
    start = time.time()

    # 1. Retrieve context
    chunks = await retrieve(question, top_k=10)
    retrieval_ms = (time.time() - start) * 1000

    # 2. Send retrieval results first
    items = [RetrievedItem(id=c.id, content=c.content, source=c.source,
             score_type=c.score_type, score=c.score) for c in chunks]
    yield f"data: {json.dumps({'type': 'retrieval', 'data': [i.model_dump() for i in items]}, ensure_ascii=False)}\n\n"

    # 3. Build prompt
    context = "\n---\n".join(c.content for c in chunks)
    messages = [
        {"role": "system", "content": f"你是NovaTech技术助手。基于以下上下文回答：\n\n{context}"},
        {"role": "user", "content": question},
    ]

    # 4. Stream LLM tokens
    llm = get_llm()
    token_count = 0
    async for token in llm.astream(messages):
        token_count += 1
        event = SSEToken(content=token)
        yield f"data: {json.dumps(event.model_dump(), ensure_ascii=False)}\n\n"

    # 5. Send done event
    done = SSEResponseInfo(
        session_id=session_id,
        retrieval_time_ms=retrieval_ms,
        tokens=token_count,
    )
    yield f"data: {json.dumps(done.model_dump(), ensure_ascii=False)}\n\n"


@router.post("/chat/message")
async def chat_message(req: ChatRequest):
    session_id = req.session_id or str(uuid.uuid4())
    return StreamingResponse(
        event_stream(req.message, session_id),
        media_type="text/event-stream",
    )
```

Update `Nova Agent/backend/app/api/v1/router.py`:
```python
from fastapi import APIRouter
from app.api.v1 import health, chat

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(chat.router, tags=["chat"])
```

Run: `cd Nova Agent/backend && python -m pytest tests/test_chat_api.py -v`
Expected: PASSED

- [ ] **Step 3: Commit**

```bash
cd "D:/claudecode_project/Nova Agent" && git add backend/app/api/v1/chat.py backend/app/api/v1/router.py backend/tests/test_chat_api.py && git commit -m "feat(backend): add SSE chat endpoint with streaming LLM responses"
```

---

## Task 8: Frontend — Initial Setup & Theme

**Files:**
- Create: `Nova Agent/frontend/src/main.tsx`
- Create: `Nova Agent/frontend/src/App.tsx`
- Create: `Nova Agent/frontend/src/styles/globals.css`
- Create: `Nova Agent/frontend/src/styles/cyberpunk.css`
- Create: `Nova Agent/frontend/src/types/index.ts`
- Create: `Nova Agent/frontend/src/stores/chatStore.ts`

**Interfaces:**
- Produces: Zustand chat store with messages, addMessage, streaming state
- Produces: Cyberpunk global CSS with neon glow effects

- [ ] **Step 1: Write application entry and theme**

Write `Nova Agent/frontend/src/main.tsx`:
```tsx
import React from "react"
import ReactDOM from "react-dom/client"
import App from "./App"
import "./styles/globals.css"

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
)
```

Write `Nova Agent/frontend/src/styles/globals.css`:
```css
@tailwind base;
@tailwind components;
@tailwind utilities;

body {
  margin: 0;
  background: #0a0a0f;
  color: #e0e0e0;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  -webkit-font-smoothing: antialiased;
}

::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: #12121a; }
::-webkit-scrollbar-thumb { background: #1e1e2e; border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: #00f0f0; }

@layer utilities {
  .neon-cyan { box-shadow: 0 0 5px #00f0f0, 0 0 20px #00f0f055; }
  .neon-pink { box-shadow: 0 0 5px #ff006e, 0 0 20px #ff006e55; }
  .neon-border { border: 1px solid #00f0f0; box-shadow: 0 0 5px #00f0f033; }
  .glass { background: rgba(18, 18, 26, 0.8); backdrop-filter: blur(12px); }
}
```

Write `Nova Agent/frontend/src/styles/cyberpunk.css`:
```css
/* Cyberpunk animations */
@keyframes glow-pulse {
  0%, 100% { opacity: 1; box-shadow: 0 0 5px #00f0f0, 0 0 20px #00f0f055; }
  50% { opacity: 0.8; box-shadow: 0 0 20px #00f0f0, 0 0 60px #00f0f088; }
}

@keyframes float-up {
  from { transform: translateY(20px); opacity: 0; }
  to { transform: translateY(0); opacity: 1; }
}

@keyframes typing-cursor {
  0%, 100% { border-color: #00f0f0; }
  50% { border-color: transparent; }
}

.glow-pulse { animation: glow-pulse 2s ease-in-out infinite; }
.float-up { animation: float-up 0.4s ease-out; }
```

Write `Nova Agent/frontend/src/types/index.ts`:
```tsx
export interface Message {
  id: string
  role: "user" | "assistant" | "system"
  content: string
  streaming?: boolean
  retrieval?: RetrievedChunk[]
}

export interface RetrievedChunk {
  id: string
  content: string
  source: string
  score_type: string
  score: number
}
```

Write `Nova Agent/frontend/src/stores/chatStore.ts`:
```ts
import { create } from "zustand"
import type { Message } from "../types"

interface ChatState {
  messages: Message[]
  sessionId: string
  isStreaming: boolean
  addMessage: (msg: Message) => void
  updateLastMessage: (content: string, streaming?: boolean) => void
  setSessionId: (id: string) => void
  setIsStreaming: (v: boolean) => void
  clearMessages: () => void
}

export const useChatStore = create<ChatState>((set) => ({
  messages: [],
  sessionId: "",
  isStreaming: false,
  addMessage: (msg) => set((s) => ({ messages: [...s.messages, msg] })),
  updateLastMessage: (content, streaming) =>
    set((s) => ({
      messages: s.messages.map((m, i) =>
        i === s.messages.length - 1 ? { ...m, content, streaming } : m
      ),
    })),
  setSessionId: (id) => set({ sessionId: id }),
  setIsStreaming: (v) => set({ isStreaming: v }),
  clearMessages: () => set({ messages: [] }),
}))
```

Write `Nova Agent/frontend/src/App.tsx` (placeholder for now):
```tsx
export default function App() {
  return (
    <div className="h-screen flex items-center justify-center bg-cyber-bg">
      <h1 className="text-cyber-cyan text-2xl font-bold glow-pulse">
        NovaTech Agent
      </h1>
    </div>
  )
}
```

- [ ] **Step 2: Install dependencies and verify build**

```bash
cd "D:/claudecode_project/Nova Agent/frontend" && npm install && npx tsc --noEmit
```

Expected: No TypeScript errors

- [ ] **Step 3: Commit**

```bash
cd "D:/claudecode_project/Nova Agent" && git add frontend/src/ && git commit -m "feat(frontend): setup React entry, cyberpunk theme, chat store"
```

---

## Task 9: Frontend — Layout Components (Sidebar + MainContent)

**Files:**
- Create: `Nova Agent/frontend/src/components/layout/Sidebar.tsx`
- Create: `Nova Agent/frontend/src/components/layout/MainContent.tsx`
- Create: `Nova Agent/frontend/src/components/layout/Header.tsx`
- Modify: `Nova Agent/frontend/src/App.tsx`

**Interfaces:**
- Produces: Sidebar with nav items (对话/知识库/记忆/任务)
- Produces: MainContent children wrapper

- [ ] **Step 1: Write layout components**

Write `Nova Agent/frontend/src/components/layout/Header.tsx`:
```tsx
import { motion } from "framer-motion"

export default function Header() {
  return (
    <header className="h-14 border-b border-cyber-border flex items-center justify-between px-6">
      <div className="flex items-center gap-3">
        <div className="w-8 h-8 rounded-lg neon-border flex items-center justify-center">
          <span className="text-cyber-cyan font-bold text-sm">N</span>
        </div>
        <h1 className="text-cyber-text font-bold tracking-wider">NOVATECH</h1>
      </div>
      <div className="flex items-center gap-2">
        <span className="w-2 h-2 rounded-full bg-cyber-cyan glow-pulse" />
        <span className="text-cyber-textDim text-xs">ONLINE</span>
      </div>
    </header>
  )
}
```

Write `Nova Agent/frontend/src/components/layout/Sidebar.tsx`:
```tsx
import { motion } from "framer-motion"
import { MessageSquare, BookOpen, Brain, Wrench } from "lucide-react"

const navItems = [
  { icon: MessageSquare, label: "对话", active: true },
  { icon: BookOpen, label: "知识库", active: false },
  { icon: Brain, label: "记忆", active: false },
  { icon: Wrench, label: "任务", active: false },
]

export default function Sidebar() {
  return (
    <aside className="w-60 border-r border-cyber-border glass flex flex-col">
      <nav className="flex-1 p-4 space-y-2">
        {navItems.map((item) => (
          <motion.button
            key={item.label}
            whileHover={{ x: 4 }}
            className={`w-full flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${
              item.active
                ? "bg-cyber-cyan/10 text-cyber-cyan neon-border"
                : "text-cyber-textDim hover:text-cyber-text hover:bg-cyber-surface"
            }`}
          >
            <item.icon size={18} />
            <span className="text-sm">{item.label}</span>
          </motion.button>
        ))}
      </nav>
    </aside>
  )
}
```

Write `Nova Agent/frontend/src/components/layout/MainContent.tsx`:
```tsx
import type { ReactNode } from "react"

export default function MainContent({ children }: { children: ReactNode }) {
  return (
    <main className="flex-1 flex flex-col overflow-hidden bg-cyber-bg">
      {children}
    </main>
  )
}
```

Update `Nova Agent/frontend/src/App.tsx`:
```tsx
import Header from "./components/layout/Header"
import Sidebar from "./components/layout/Sidebar"
import MainContent from "./components/layout/MainContent"

export default function App() {
  return (
    <div className="h-screen flex flex-col bg-cyber-bg">
      <Header />
      <div className="flex-1 flex overflow-hidden">
        <Sidebar />
        <MainContent>
          <div className="flex-1 flex items-center justify-center">
            <h2 className="text-cyber-textDim">对话组件加载中...</h2>
          </div>
        </MainContent>
      </div>
    </div>
  )
}
```

Run:
```bash
cd "D:/claudecode_project/Nova Agent/frontend" && npx tsc --noEmit
```
Expected: No errors

- [ ] **Step 2: Commit**

```bash
cd "D:/claudecode_project/Nova Agent" && git add frontend/src/components/ frontend/src/App.tsx && git commit -m "feat(frontend): add cyberpunk layout (Header, Sidebar, MainContent)"
```

---

## Task 10: Frontend — Chat UI Components

**Files:**
- Create: `Nova Agent/frontend/src/components/chat/MessageBubble.tsx`
- Create: `Nova Agent/frontend/src/components/chat/InputBox.tsx`
- Create: `Nova Agent/frontend/src/components/chat/TypingIndicator.tsx`
- Create: `Nova Agent/frontend/src/components/chat/ChatWindow.tsx`
- Create: `Nova Agent/frontend/src/hooks/useSSE.ts`
- Modify: `Nova Agent/frontend/src/App.tsx`

**Interfaces:**
- Produces: ChatWindow with message rendering + SSE streaming
- Produces: useSSE hook for API connection

- [ ] **Step 1: Write SSE hook**

Write `Nova Agent/frontend/src/hooks/useSSE.ts`:
```ts
import { useCallback } from "react"
import { useChatStore } from "../stores/chatStore"

export function useSSE() {
  const { addMessage, updateLastMessage, setSessionId, setIsStreaming } = useChatStore.getState()

  const sendMessage = useCallback(async (text: string) => {
    const store = useChatStore.getState()
    const sessionId = store.sessionId

    addMessage({ id: crypto.randomUUID(), role: "user", content: text })
    addMessage({ id: crypto.randomUUID(), role: "assistant", content: "", streaming: true })
    setIsStreaming(true)

    const res = await fetch("/api/v1/chat/message", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, session_id: sessionId }),
    })

    const reader = res.body!.getReader()
    const decoder = new TextDecoder()
    let buffer = ""

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      const lines = buffer.split("\n\n")
      buffer = lines.pop() || ""

      for (const line of lines) {
        if (!line.startsWith("data: ")) continue
        const data = JSON.parse(line.slice(6))

        if (data.type === "retrieval") {
          // could update retrieval panel
        } else if (data.type === "token") {
          useChatStore.getState().updateLastMessage(
            useChatStore.getState().messages.at(-1)!.content + data.content,
            true
          )
        } else if (data.type === "done") {
          setSessionId(data.session_id)
          updateLastMessage(useChatStore.getState().messages.at(-1)!.content, false)
          setIsStreaming(false)
        }
      }
    }
  }, [])

  return { sendMessage }
}
```

- [ ] **Step 2: Write chat components**

Write `Nova Agent/frontend/src/components/chat/MessageBubble.tsx`:
```tsx
import { motion } from "framer-motion"
import type { Message } from "../../types"

export default function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === "user"
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className={`flex ${isUser ? "justify-end" : "justify-start"} mb-4`}
    >
      <div
        className={`max-w-[70%] px-4 py-3 rounded-2xl text-sm leading-relaxed ${
          isUser
            ? "bg-cyber-purple/20 text-cyber-text border border-cyber-purple/30"
            : "bg-cyber-surface text-cyber-text border border-cyber-border"
        }`}
      >
        <p className="whitespace-pre-wrap">{message.content}</p>
        {message.streaming && (
          <span className="inline-block w-2 h-4 ml-1 bg-cyber-cyan animate-pulse" />
        )}
      </div>
    </motion.div>
  )
}
```

Write `Nova Agent/frontend/src/components/chat/TypingIndicator.tsx`:
```tsx
import { motion } from "framer-motion"

export default function TypingIndicator() {
  return (
    <div className="flex gap-1 px-4 py-3">
      {[0, 1, 2].map((i) => (
        <motion.div
          key={i}
          className="w-2 h-2 rounded-full bg-cyber-cyan"
          animate={{ y: [0, -6, 0] }}
          transition={{ duration: 0.6, repeat: Infinity, delay: i * 0.15 }}
        />
      ))}
    </div>
  )
}
```

Write `Nova Agent/frontend/src/components/chat/InputBox.tsx`:
```tsx
import { useState } from "react"
import { motion } from "framer-motion"
import { Send } from "lucide-react"
import { useChatStore } from "../../stores/chatStore"

interface Props {
  onSend: (text: string) => void
}

export default function InputBox({ onSend }: Props) {
  const [text, setText] = useState("")
  const isStreaming = useChatStore((s) => s.isStreaming)

  const handleSubmit = () => {
    if (!text.trim() || isStreaming) return
    onSend(text)
    setText("")
  }

  return (
    <div className="p-6 border-t border-cyber-border">
      <motion.div
        className="flex items-center gap-3 px-4 py-3 rounded-xl bg-cyber-surface border border-cyber-border focus-within:neon-border transition-all"
        animate={isStreaming ? { opacity: [1, 0.7, 1] } : { opacity: 1 }}
        transition={{ duration: 1.5, repeat: isStreaming ? Infinity : 0 }}
      >
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
          placeholder="输入你的技术问题..."
          className="flex-1 bg-transparent outline-none text-cyber-text text-sm placeholder:text-cyber-textDim"
          disabled={isStreaming}
        />
        <button
          onClick={handleSubmit}
          disabled={isStreaming || !text.trim()}
          className="text-cyber-cyan disabled:text-cyber-textDim transition-colors"
        >
          <Send size={20} />
        </button>
      </motion.div>
    </div>
  )
}
```

Write `Nova Agent/frontend/src/components/chat/ChatWindow.tsx`:
```tsx
import { useRef, useEffect } from "react"
import MessageBubble from "./MessageBubble"
import InputBox from "./InputBox"
import TypingIndicator from "./TypingIndicator"
import { useChatStore } from "../../stores/chatStore"
import { useSSE } from "../../hooks/useSSE"

export default function ChatWindow() {
  const messages = useChatStore((s) => s.messages)
  const isStreaming = useChatStore((s) => s.isStreaming)
  const { sendMessage } = useSSE()
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" })
  }, [messages])

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <div ref={scrollRef} className="flex-1 overflow-y-auto p-6">
        {messages.length === 0 && (
          <div className="h-full flex items-center justify-center">
            <h2 className="text-cyber-textDim text-lg">开始你的技术探索之旅...</h2>
          </div>
        )}
        {messages.map((msg) => (
          <MessageBubble key={msg.id} message={msg} />
        ))}
        {isStreaming && !useChatStore.getState().messages.at(-1)?.streaming && (
          <TypingIndicator />
        )}
      </div>
      <InputBox onSend={sendMessage} />
    </div>
  )
}
```

Update `Nova Agent/frontend/src/App.tsx`:
```tsx
import Header from "./components/layout/Header"
import Sidebar from "./components/layout/Sidebar"
import MainContent from "./components/layout/MainContent"
import ChatWindow from "./components/chat/ChatWindow"

export default function App() {
  return (
    <div className="h-screen flex flex-col bg-cyber-bg">
      <Header />
      <div className="flex-1 flex overflow-hidden">
        <Sidebar />
        <MainContent>
          <ChatWindow />
        </MainContent>
      </div>
    </div>
  )
}
```

Run:
```bash
cd "D:/claudecode_project/Nova Agent/frontend" && npx tsc --noEmit
```

- [ ] **Step 3: Commit**

```bash
cd "D:/claudecode_project/Nova Agent" && git add frontend/ && git commit -m "feat(frontend): add chat UI with SSE streaming, cyberpunk animations"
```

---

## Task 11: Frontend — Three.js Particle Background

**Files:**
- Create: `Nova Agent/frontend/src/components/particles/ParticleField.tsx`

**Interfaces:**
- Produces: Three.js animated particle field background

- [ ] **Step 1: Write particle background**

Write `Nova Agent/frontend/src/components/particles/ParticleField.tsx`:
```tsx
import { useRef, useMemo } from "react"
import { Canvas, useFrame } from "@react-three/fiber"
import * as THREE from "three"

function Particles({ count = 500 }) {
  const mesh = useRef<THREE.Points>(null!)

  const positions = useMemo(() => {
    const pos = new Float32Array(count * 3)
    for (let i = 0; i < count; i++) {
      pos[i * 3] = (Math.random() - 0.5) * 20
      pos[i * 3 + 1] = (Math.random() - 0.5) * 20
      pos[i * 3 + 2] = (Math.random() - 0.5) * 10
    }
    return pos
  }, [count])

  useFrame((state) => {
    if (mesh.current) {
      mesh.current.rotation.y = state.clock.elapsedTime * 0.02
      mesh.current.rotation.x = Math.sin(state.clock.elapsedTime * 0.01) * 0.1
    }
  })

  return (
    <points ref={mesh}>
      <bufferGeometry>
        <bufferAttribute
          attach="attributes-position"
          count={count}
          array={positions}
          itemSize={3}
        />
      </bufferGeometry>
      <pointsMaterial
        size={0.03}
        color="#00f0f0"
        transparent
        opacity={0.6}
        sizeAttenuation
      />
    </points>
  )
}

export default function ParticleField() {
  return (
    <div className="absolute inset-0 pointer-events-none z-0">
      <Canvas camera={{ position: [0, 0, 5], fov: 60 }}>
        <Particles count={600} />
      </Canvas>
    </div>
  )
}
```

Update `Nova Agent/frontend/src/App.tsx` to include particles:
```tsx
import Header from "./components/layout/Header"
import Sidebar from "./components/layout/Sidebar"
import MainContent from "./components/layout/MainContent"
import ChatWindow from "./components/chat/ChatWindow"
import ParticleField from "./components/particles/ParticleField"

export default function App() {
  return (
    <div className="h-screen flex flex-col bg-cyber-bg relative">
      <ParticleField />
      <Header />
      <div className="flex-1 flex overflow-hidden z-10">
        <Sidebar />
        <MainContent>
          <ChatWindow />
        </MainContent>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Verify build**

```bash
cd "D:/claudecode_project/Nova Agent/frontend" && npx tsc --noEmit && npx vite build
```

Expected: Build successful

- [ ] **Step 3: Commit**

```bash
cd "D:/claudecode_project/Nova Agent" && git add frontend/src/components/particles/ frontend/src/App.tsx && git commit -m "feat(frontend): add Three.js cyberpunk particle background"
```

---

## Task 12: End-to-End Integration & Final Verification

**Files:**
- Modify: `Nova Agent/backend/app/api/v1/router.py` (add all knowledge/memory routes as stubs)
- Create: `Nova Agent/backend/app/api/v1/knowledge.py`
- Create: `Nova Agent/backend/app/api/v1/memory.py`
- Create: `Nova Agent/frontend/public/vite.svg`

- [ ] **Step 1: Add stub routes for knowledge and memory**

Write `Nova Agent/backend/app/api/v1/knowledge.py`:
```python
from fastapi import APIRouter
router = APIRouter()

@router.get("/knowledge/list")
async def list_docs():
    return {"documents": []}

@router.post("/knowledge/upload")
async def upload_doc():
    return {"status": "ok", "message": "上传功能将在后续版本实现"}


@router.delete("/knowledge/{doc_id}")
async def delete_doc(doc_id: str):
    return {"status": "ok"}
```

Write `Nova Agent/backend/app/api/v1/memory.py`:
```python
from fastapi import APIRouter
router = APIRouter()

@router.get("/memory/summary")
async def memory_summary():
    return {"memories": [], "message": "记忆功能将在后续版本实现"}
```

Update `Nova Agent/backend/app/api/v1/router.py`:
```python
from fastapi import APIRouter
from app.api.v1 import health, chat, knowledge, memory

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(chat.router, tags=["chat"])
api_router.include_router(knowledge.router, tags=["knowledge"])
api_router.include_router(memory.router, tags=["memory"])
```

- [ ] **Step 2: Run all backend tests**

```bash
cd Nova Agent/backend && python -m pytest tests/ -v
```
Expected: All PASSED

- [ ] **Step 3: Final manual verification**

```bash
# Terminal 1 — start backend
cd Nova Agent/backend && python -m uvicorn app.main:app --reload --port 8000

# Terminal 2 — start frontend
cd Nova Agent/frontend && npm run dev
```

Verify:
- `curl http://localhost:8000/api/v1/health` → `{"status":"ok","version":"0.1.0"}`
- Browser opens `http://localhost:5173` → cyberpunk layout with particle background
- Sidebar shows nav items
- Chat window shows placeholder
- All TypeScript compiles cleanly

- [ ] **Step 4: Final commit**

```bash
cd "D:/claudecode_project/Nova Agent" && git add . && git commit -m "feat: MVP complete — cyberpunk UI, three-way retrieval, LLM fallback chain"
```

---

## Spec Coverage Checklist

| Spec Requirement | Task(s) |
|-----------------|---------|
| FastAPI backend with CORS | Task 2 |
| Three-way retrieval (Qdrant+PG+Neo4j) | Task 5 |
| RRF fusion algorithm | Task 3 |
| Embedding module (DashScope/OpenAI) | Task 4 |
| LLM fallback chain (Longcat→DeepSeek→DashScope) | Task 6 |
| SSE chat streaming endpoint | Task 7 |
| React+TS+Vite frontend | Task 1, 8 |
| Cyberpunk TailwindCSS theme | Task 8, 9 |
| Three.js particle background | Task 11 |
| Left-right split layout | Task 9 |
| Chat UI with typing animation | Task 10 |
| SSE hook for streaming | Task 10 |
| Knowledge & Memory stubs | Task 12 | 
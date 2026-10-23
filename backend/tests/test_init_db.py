"""Integration tests for database initialization (requires live PG + Qdrant)."""
import pytest
import psycopg
from qdrant_client import QdrantClient
from qdrant_client.models import Distance

from app.config import settings
from app.db.init_db import check_connectivity, init_all, init_postgres, init_qdrant

pytestmark = pytest.mark.integration

EXPECTED_TABLES = {
    "users", "sessions", "messages", "facts",
    "repos", "repo_files", "symbols", "chunks",
    "usage_log", "audit_log",
}


@pytest.mark.asyncio
async def test_check_connectivity_reports_pg_and_qdrant():
    result = await check_connectivity()
    assert "postgres" in result and "qdrant" in result


@pytest.mark.asyncio
async def test_init_postgres_creates_all_tables():
    status = await init_postgres()
    assert status in ("created", "already_exists")

    with psycopg.connect(settings.postgres_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname='public'"
            )
            tables = {row[0] for row in cur.fetchall()}
    assert EXPECTED_TABLES.issubset(tables)


@pytest.mark.asyncio
async def test_init_postgres_idempotent():
    first = await init_postgres()
    assert first in ("created", "already_exists")
    second = await init_postgres()
    assert second == "already_exists"


@pytest.mark.asyncio
async def test_init_qdrant_collection_shape():
    status = await init_qdrant()
    assert status in ("created", "already_exists")

    client = QdrantClient(url=settings.qdrant_url)
    info = client.get_collection(settings.qdrant_collection)
    assert info.config.params.vectors.size == settings.embedding_dim
    assert info.config.params.vectors.distance == Distance.COSINE


@pytest.mark.asyncio
async def test_init_all_seeds_users_and_reports_status():
    result = await init_all()
    assert result["postgres"] in ("created", "already_exists")
    assert result["qdrant"] in ("created", "already_exists")
    assert str(result.get("users", "")).startswith("seeded:")

    with psycopg.connect(settings.postgres_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT username, role FROM users ORDER BY role")
            users = dict(cur.fetchall())
    assert users.get(settings.demo_username) == "demo"
    assert users.get(settings.admin_username) == "admin"
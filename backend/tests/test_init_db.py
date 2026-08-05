"""Tests for the one-click database initialization module (app.db.init_db)."""
import pytest
import psycopg
from qdrant_client import QdrantClient
from qdrant_client.models import Distance

from app.config import settings
from app.db.init_db import (
    init_all,
    init_postgres,
    init_qdrant,
    init_neo4j,
    check_connectivity,
)


@pytest.mark.asyncio
async def test_check_connectivity_returns_status():
    """check_connectivity() must report status for all three databases."""
    result = await check_connectivity()
    assert "postgres" in result
    assert "qdrant" in result
    assert "neo4j" in result
    assert len(result) == 3


@pytest.mark.asyncio
async def test_init_postgres_creates_tables():
    """init_postgres() must create documents + agent_facts and be idempotent."""
    status = await init_postgres()
    assert status in ("created", "already_exists")

    with psycopg.connect(settings.postgres_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname='public' AND tablename IN ('documents', 'agent_facts')"
            )
            tables = {row[0] for row in cur.fetchall()}
            assert "documents" in tables
            assert "agent_facts" in tables


@pytest.mark.asyncio
async def test_init_qdrant_creates_collection():
    """init_qdrant() must ensure novatech_docs collection exists with the
    expected vector size (1024) and distance metric (Cosine)."""
    status = await init_qdrant()
    assert status in ("created", "already_exists")

    client = QdrantClient(url=settings.qdrant_url)
    info = client.get_collection("novatech_docs")
    assert info is not None
    assert info.config.params.vectors.size == 1024
    assert info.config.params.vectors.distance == Distance.COSINE


@pytest.mark.asyncio
async def test_init_postgres_idempotent():
    """init_postgres() run twice must not error and must report
    "already_exists" on the second run."""
    first = await init_postgres()
    assert first in ("created", "already_exists")

    second = await init_postgres()
    assert second == "already_exists"


@pytest.mark.asyncio
async def test_init_neo4j_runs():
    """init_neo4j() must run without raising an error."""
    status = await init_neo4j()
    assert status == "ok"


@pytest.mark.asyncio
async def test_init_all_end_to_end():
    """init_all() must run all three initializers and report their status."""
    result = await init_all()
    assert "connectivity" in result
    assert "postgres" in result
    assert "qdrant" in result
    assert "neo4j" in result
    assert result["postgres"] in ("created", "already_exists")
    assert result["qdrant"] in ("created", "already_exists")
    assert result["neo4j"] == "ok"

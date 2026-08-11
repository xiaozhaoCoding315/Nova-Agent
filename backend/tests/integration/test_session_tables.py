import pytest
from app.db import query
from app.db.init_db import init_postgres


@pytest.mark.asyncio
@pytest.mark.integration
async def test_session_tables_exist():
    await init_postgres()
    for table in ("chat_sessions", "chat_messages"):
        rows = await query(
            "SELECT EXISTS(SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename=%s)",
            (table,),
        )
        assert rows and rows[0][0], f"table {table} missing"

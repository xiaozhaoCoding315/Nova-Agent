"""PostgreSQL sync wrapper — runs sync psycopg in async thread pool."""
import asyncio
import psycopg
from app.config import settings


def _execute(sql: str, params: tuple = None, commit: bool = False) -> list:
    """Execute a query and return results.

    For read-only queries (commit=False), no commit is issued.
    For write queries (commit=True), commits after execution — needed for
    INSERT/UPDATE/DELETE and also for INSERT ... RETURNING.
    """
    with psycopg.connect(settings.postgres_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            try:
                result = cur.fetchall()
            except psycopg.ProgrammingError:
                result = []
        if commit:
            conn.commit()
    return result


def _execute_many(queries: list[tuple]) -> None:
    """Execute multiple (sql, params) in a single transaction."""
    with psycopg.connect(settings.postgres_dsn) as conn:
        with conn.cursor() as cur:
            for sql, params in queries:
                cur.execute(sql, params)
        conn.commit()


async def query(sql: str, params: tuple = None) -> list:
    """Async wrapper: run read-only SQL query in thread pool."""
    return await asyncio.to_thread(_execute, sql, params)


async def execute(sql: str, params: tuple = None) -> list:
    """Async wrapper: run SQL insert/update/delete in thread pool.

    Returns rows if the statement uses RETURNING, otherwise [].
    """
    return await asyncio.to_thread(_execute, sql, params, commit=True)


async def transaction(queries: list[tuple]) -> None:
    """Async wrapper: run multiple SQL in a transaction."""
    await asyncio.to_thread(_execute_many, queries)

"""Hourly memory maintenance entrypoint (called by the app cleanup loop)."""
from app.core.memory.facts import run_cleanup as _facts_cleanup


async def run_cleanup() -> dict:
    return await _facts_cleanup()
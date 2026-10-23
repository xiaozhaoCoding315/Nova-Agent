"""Hourly memory maintenance entrypoint (called by the app cleanup loop)."""
from app.core.memory import daily, facts


async def run_cleanup() -> dict:
    result = await facts.run_cleanup()
    result["facts_promoted"] = await facts.promote_facts()
    try:
        result["daily_summaries"] = await daily.rollup_yesterday()
    except Exception:  # noqa: BLE001
        result["daily_summaries"] = 0
    return result

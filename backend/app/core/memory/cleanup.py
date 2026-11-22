"""Hourly memory maintenance entrypoint (called by the app cleanup loop)."""
from datetime import date

from app.core.memory import daily, facts

# Deterministic consolidation runs at most once per calendar day; the hourly
# loop keeps TTL/decay/promotion frequent without paying for an O(n²) pass.
_last_consolidated: date | None = None


async def run_cleanup() -> dict:
    global _last_consolidated
    result = await facts.run_cleanup()
    result["facts_promoted"] = await facts.promote_facts()
    today = date.today()
    if _last_consolidated != today:
        try:
            result["facts_consolidated"] = await facts.consolidate_duplicates()
            _last_consolidated = today
        except Exception:  # noqa: BLE001
            result["facts_consolidated"] = 0
    try:
        result["daily_summaries"] = await daily.rollup_yesterday()
    except Exception:  # noqa: BLE001
        result["daily_summaries"] = 0
    return result

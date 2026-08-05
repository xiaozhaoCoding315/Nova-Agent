"""Automatically archive session facts to persistent memory on session end."""
import asyncio
from app.core.memory.extractor import extract_facts
from app.core.memory.dedup import dedup_facts
from app.core.memory.store import save_fact
from app.core.memory.session import get_history, clear_session
from app.core.memory.graph_memory import integrate_fact_to_graph, build_learning_trajectory


async def archive_session(session_id: str) -> dict:
    """Extract, dedup, persist facts from a session. Returns extraction summary."""
    history = get_history(session_id, last_n=20)

    if len(history) < 2:
        clear_session(session_id)
        return {"archived": 0, "message": "Not enough messages to archive"}

    # Extract facts
    raw_facts = await extract_facts(history)
    if not raw_facts:
        clear_session(session_id)
        return {"archived": 0, "message": "No facts extracted"}

    # Deduplicate
    unique_facts = await dedup_facts(raw_facts, session_id)

    # Save to persistent store + build graph relationships
    saved_count = 0
    for fact in unique_facts:
        try:
            await save_fact(
                session_id,
                fact["fact"],
                fact.get("category", "general"),
                importance=0.6
            )
            # Integrate into knowledge graph
            await integrate_fact_to_graph(session_id, fact["fact"], fact.get("category", "general"))
            saved_count += 1
        except Exception:
            continue

    # Build learning trajectory (FOLLOWS relationships)
    await build_learning_trajectory(session_id)

    # Clear from memory
    clear_session(session_id)

    return {
        "archived": saved_count,
        "extracted": len(raw_facts),
        "deduplicated": len(raw_facts) - len(unique_facts),
    }

"""Dynamic context assembly: build personalized prompt context from memory."""
from app.core.memory.store import get_facts


# Note: Layer 4 (runtime state memory — DAG node state, task resumption) is
# intentionally deferred. It requires persistent state machine storage and
# is out of scope for this iteration. Layers 1-3 cover the core use case.
async def assemble_context(query: str, session_id: str) -> str:
    """Assemble multi-layer context: session history + long-term facts + graph memory."""
    parts = []
    # Layer 1: Session history (short-term)
    from app.core.memory.session import get_history
    history = await get_history(session_id, last_n=10)
    if history:
        hist_text = "\n".join(f"{m['role']}: {m['content']}" for m in history)
        parts.append(f"## 近期对话\n{hist_text}")
    # Layer 2: Long-term facts
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


async def check_should_archive(session_id: str, msg_count: int = 10) -> bool:
    """Check if a session should be auto-archived based on message count."""
    from app.core.memory.session import get_summary
    summary = await get_summary(session_id)
    return summary["message_count"] >= msg_count

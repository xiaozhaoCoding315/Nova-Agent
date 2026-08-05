import uuid
from datetime import datetime
_SESSIONS: dict[str, dict] = {}

def get_or_create_session(session_id=None) -> dict:
    if not session_id or session_id not in _SESSIONS:
        session_id = session_id or str(uuid.uuid4())
        _SESSIONS[session_id] = {"id": session_id, "messages": [], "created_at": datetime.now().isoformat()}
    return _SESSIONS[session_id]

def add_message(session_id: str, role: str, content: str):
    session = get_or_create_session(session_id)
    session["messages"].append({"role": role, "content": content[:2000], "timestamp": datetime.now().isoformat()})
    if len(session["messages"]) > 20:
        session["messages"] = session["messages"][-20:]

def get_history(session_id: str, last_n: int = 10) -> list[dict]:
    return get_or_create_session(session_id)["messages"][-last_n:]

def get_summary(session_id: str) -> dict:
    s = get_or_create_session(session_id)
    return {"session_id": session_id, "message_count": len(s["messages"]), "created_at": s["created_at"]}

def clear_session(session_id: str) -> bool:
    return bool(_SESSIONS.pop(session_id, None))

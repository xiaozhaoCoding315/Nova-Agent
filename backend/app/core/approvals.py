"""In-process pending tool approvals (ask mode).

A chat turn pauses on a Future until the user approves/rejects from the UI.
Single-worker deployment only; multi-worker needs a DB-backed wait queue
(same constraint as the WebSocket-style cancel path).
"""
import asyncio

_PENDING: dict[str, tuple[int, asyncio.Future]] = {}


def _key(session_id: str, tool_call_id: str) -> str:
    return f"{session_id}:{tool_call_id}"


def register(
    session_id: str, tool_call_id: str, user_id: int
) -> asyncio.Future:
    future: asyncio.Future = asyncio.get_running_loop().create_future()
    _PENDING[_key(session_id, tool_call_id)] = (int(user_id), future)
    return future


def resolve(
    session_id: str, tool_call_id: str, user_id: int, approved: bool
) -> bool:
    entry = _PENDING.get(_key(session_id, tool_call_id))
    if not entry or entry[0] != int(user_id):
        return False
    future = entry[1]
    if not future.done():
        future.set_result(approved)
    return True


def drop(session_id: str, tool_call_id: str) -> None:
    _PENDING.pop(_key(session_id, tool_call_id), None)

"""Local executor heartbeat (``nova.py agent``).

The executor polls ``/local/exec/pending`` every few seconds; that poll is the
heartbeat.  It is stored in PostgreSQL so multiple app workers agree, with a
process-local fast path for the worker that saw the poll.
"""
import time

from app.config import settings
from app.db import execute, query

_ONLINE_WINDOW_S = 30
_LAST_SEEN: dict[int, float] = {}
_db_disabled_until = 0.0


def _uid(user_id: int | str) -> int:
    return int(user_id)


async def mark_seen(user_id: int | str) -> None:
    uid = _uid(user_id)
    _LAST_SEEN[uid] = time.time()
    try:
        await execute(
            "INSERT INTO local_agent_heartbeats (user_id, last_seen_at) "
            "VALUES (%s, now()) ON CONFLICT (user_id) "
            "DO UPDATE SET last_seen_at = now()",
            (uid,),
        )
    except Exception:  # noqa: BLE001 - heartbeat must never break polling
        pass


async def last_seen_age(user_id: int | str) -> int | None:
    global _db_disabled_until
    uid = _uid(user_id)
    seen = _LAST_SEEN.get(uid)
    if seen and time.time() - seen < _ONLINE_WINDOW_S:
        return int(time.time() - seen)

    if settings.nova_test_fast:
        return int(time.time() - seen) if seen else None

    if time.time() >= _db_disabled_until:
        try:
            rows = await query(
                "SELECT EXTRACT(EPOCH FROM (now() - last_seen_at)) "
                "FROM local_agent_heartbeats WHERE user_id = %s",
                (uid,),
            )
            if rows and rows[0][0] is not None:
                age = int(float(rows[0][0]))
                if age < _ONLINE_WINDOW_S:
                    _LAST_SEEN[uid] = time.time() - age
                return age
        except Exception:  # noqa: BLE001 - table may not exist yet / DB down
            _db_disabled_until = time.time() + 60
    return int(time.time() - seen) if seen else None


async def is_online(user_id: int | str) -> bool:
    age = await last_seen_age(user_id)
    return age is not None and age < _ONLINE_WINDOW_S

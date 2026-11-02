"""Persisted SSE event log + coalescing for resumable chat turns."""
import json
import time
from typing import Any

from app.db import execute, query

TOKEN_FLUSH_CHARS = 800
FLUSH_INTERVAL_SECONDS = 0.4
TOOL_OUTPUT_LIMIT = 60_000


def sse_frame(event: str, payload: dict) -> str:
    data = json.dumps(payload, ensure_ascii=False, default=str)
    return f"event: {event}\ndata: {data}\n\n"


class EventCoalescer:
    """Merge high-frequency token/tool_output events without reordering.

    Ordering is preserved at non-coalesced boundaries and for token runs that
    follow buffered tool output.
    """

    def __init__(self) -> None:
        self._tokens: list[str] = []
        self._token_chars = 0
        self._outputs: dict[tuple[str, str], dict[str, Any]] = {}
        self._last_flush = time.monotonic()

    def feed(self, event: dict) -> list[tuple[str, dict]]:
        kind = str(event.get("event") or "message")
        data = event.get("data")
        payload = data if isinstance(data, dict) else {}

        if kind == "token":
            pending = self.flush() if self._outputs else []
            text = str(payload.get("text") or "")
            if text:
                self._tokens.append(text)
                self._token_chars += len(text)
            if self._token_chars >= TOKEN_FLUSH_CHARS:
                return pending + self.flush()
            return pending

        if kind == "tool_output":
            call_id = str(payload.get("id") or "")
            stream = str(payload.get("stream") or "stdout")
            merged = self._outputs.setdefault((call_id, stream), {
                "id": call_id,
                "name": payload.get("name"),
                "stream": stream,
                "text": "",
            })
            merged["text"] = (
                str(merged.get("text") or "") + str(payload.get("text") or "")
            )[-TOOL_OUTPUT_LIMIT:]
            return []

        return self.flush() + [(kind, payload)]

    def flush(self) -> list[tuple[str, dict]]:
        pending: list[tuple[str, dict]] = []
        if self._tokens:
            pending.append(("token", {"text": "".join(self._tokens)}))
            self._tokens = []
            self._token_chars = 0
        for output in self._outputs.values():
            pending.append(("tool_output", dict(output)))
        self._outputs = {}
        self._last_flush = time.monotonic()
        return pending

    def flush_if_due(self, now: float | None = None) -> list[tuple[str, dict]]:
        current = now if now is not None else time.monotonic()
        if (self._tokens or self._outputs) and (
            current - self._last_flush >= FLUSH_INTERVAL_SECONDS
        ):
            return self.flush()
        return []


async def append_event(
    turn_id: str, seq: int, event_type: str, payload: dict,
) -> None:
    await execute(
        "INSERT INTO turn_events (turn_id, seq, type, payload) "
        "VALUES (%s, %s, %s, %s::jsonb) "
        "ON CONFLICT (turn_id, seq) DO NOTHING",
        (
            turn_id,
            seq,
            event_type[:40],
            json.dumps(payload or {}, ensure_ascii=False, default=str),
        ),
    )


async def load_events(
    turn_id: str, after_seq: int, limit: int = 200,
) -> list[dict]:
    rows = await query(
        "SELECT seq, type, payload FROM turn_events "
        "WHERE turn_id = %s AND seq > %s ORDER BY seq ASC LIMIT %s",
        (turn_id, max(0, int(after_seq)), max(1, min(int(limit), 500))),
    )
    return [
        {"seq": int(row[0]), "type": row[1], "payload": row[2] or {}}
        for row in rows
    ]


async def max_seq(turn_id: str) -> int:
    rows = await query(
        "SELECT COALESCE(MAX(seq), 0) FROM turn_events WHERE turn_id = %s",
        (turn_id,),
    )
    return int(rows[0][0] or 0) if rows else 0

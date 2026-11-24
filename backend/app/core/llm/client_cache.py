"""Shared ``AsyncOpenAI`` clients, one per (event loop, endpoint, key).

``get_llm`` runs on every round of every turn, and each call used to build a
fresh ``AsyncOpenAI`` + ``httpx.AsyncClient``.  A 16-round turn therefore left
16 connection pools alive, none of them closed: on a 2G host that is a visible
memory cost during long tasks.  The client only depends on the endpoint and
the credential — the model is chosen per request — so it can be shared.

The cache is keyed by the running event loop as well: an ``httpx`` pool holds
sockets bound to the loop that opened them, and reusing a client from a loop
that has since closed raises "Event loop is closed".  Tests that build a
client outside any loop land in the ``None`` bucket.

Clients are never closed per call; :func:`close_clients` runs at shutdown.
"""
from __future__ import annotations

import asyncio
import hashlib

import httpx
import structlog
from openai import AsyncOpenAI

logger = structlog.get_logger()

#: (loop identity, base url, key fingerprint) → (loop object, client).
#: The loop object is kept so a recycled ``id()`` cannot hand back a client
#: bound to a loop that is already gone.
_clients: dict[tuple[int, str, str], tuple[asyncio.AbstractEventLoop | None, AsyncOpenAI]] = {}


def _fingerprint(api_key: str) -> str:
    """Short digest of the key, so the cache never holds it in a dict key."""
    return hashlib.sha256((api_key or "").encode("utf-8")).hexdigest()[:16]


def _current_loop() -> asyncio.AbstractEventLoop | None:
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


def get_client(api_key: str, base_url: str) -> AsyncOpenAI:
    """Return the shared client for this endpoint and credential."""
    loop = _current_loop()
    key = (
        id(loop) if loop is not None else 0,
        (base_url or "").strip().rstrip("/"),
        _fingerprint(api_key),
    )
    cached = _clients.get(key)
    if cached is not None:
        cached_loop, client = cached
        reusable = cached_loop is loop and not (loop is not None and loop.is_closed())
        # A caller may have closed the shared client (evals do this); never
        # hand out a closed pool.
        if reusable and not client.is_closed():
            return client
        _clients.pop(key, None)

    client = AsyncOpenAI(
        api_key=api_key or "ollama",
        base_url=base_url,
        http_client=httpx.AsyncClient(follow_redirects=False),
    )
    _clients[key] = (loop, client)
    return client


async def close_clients() -> None:
    """Close every cached pool.  Safe to call more than once."""
    entries = list(_clients.values())
    _clients.clear()
    for _, client in entries:
        try:
            await client.close()
        except Exception:  # noqa: BLE001 — shutdown must not raise
            logger.debug("llm_client_close_failed", exc_info=True)


def cached_client_count() -> int:
    """Observable for tests and diagnostics."""
    return len(_clients)

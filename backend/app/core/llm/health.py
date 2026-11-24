"""In-process provider health memory.

``FallbackLLM`` walks its chain on every request.  Without health memory a
dead primary keeps costing a full timeout on every single turn, because
nothing remembers that the last five attempts all failed at the same host.

The rules are deliberately soft:

- ``FAILURE_THRESHOLD`` consecutive failures mark a provider down;
- down lasts ``COOLDOWN_SECONDS``, then the provider is tried again;
- any success clears its counter;
- if **every** provider is down, the chain is still walked — a recovering
  provider is a better bet than a guaranteed error.

State is per process and per provider id.  This is a hint for ordering, not
a source of truth: nothing here decides that a request must fail.
"""
import time

import structlog

logger = structlog.get_logger()

FAILURE_THRESHOLD = 3
COOLDOWN_SECONDS = 30.0

_failures: dict[str, int] = {}
_down_until: dict[str, float] = {}


def reset() -> None:
    _failures.clear()
    _down_until.clear()


def provider_key(provider) -> str:
    """Stable id for a provider instance (falls back to its class name).

    A plain string is passed through, so callers holding only an id (health
    endpoints, tests) do not need a live instance.
    """
    if isinstance(provider, str):
        return provider
    pid = getattr(provider, "provider_id", "") or ""
    if pid:
        return str(pid)
    return type(provider).__name__


def record_success(provider) -> None:
    key = provider_key(provider)
    _failures.pop(key, None)
    _down_until.pop(key, None)


def record_failure(provider, exc: Exception | None = None) -> None:
    key = provider_key(provider)
    count = _failures.get(key, 0) + 1
    _failures[key] = count
    if count >= FAILURE_THRESHOLD:
        _down_until[key] = time.time() + COOLDOWN_SECONDS
        logger.warning(
            "llm_provider_marked_down",
            provider=key, failures=count, cooldown_s=COOLDOWN_SECONDS,
            error=str(exc)[:200] if exc else "",
        )


def mark_down(provider, seconds: float = COOLDOWN_SECONDS) -> None:
    _down_until[provider_key(provider)] = time.time() + max(0.0, seconds)


def is_available(provider) -> bool:
    until = _down_until.get(provider_key(provider))
    return until is None or time.time() >= until


def failures(provider) -> int:
    return _failures.get(provider_key(provider), 0)


def order_chain(providers: list) -> list:
    """Healthy providers first, preserving relative order; all-down → as-is."""
    healthy = [p for p in providers if is_available(p)]
    if not healthy:
        return list(providers)
    unhealthy = [p for p in providers if not is_available(p)]
    return healthy + unhealthy


def snapshot() -> dict[str, dict]:
    """For /status/health and diagnostics: no secrets, just counters."""
    now = time.time()
    return {
        key: {
            "failures": count,
            "down_for_s": round(max(0.0, _down_until.get(key, 0.0) - now), 1),
        }
        for key, count in _failures.items()
    }

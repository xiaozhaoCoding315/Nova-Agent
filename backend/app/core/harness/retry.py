"""Exponential backoff retry with timeout enforcement.

Three rules keep retries from making an outage worse:

1. **Only transient failures are retried.** HTTP status is the primary signal
   (``429``/``5xx``/``408``), and account-level failures — exhausted quota,
   invalid key, context too long — are never retried: waiting cannot fix them.
2. **The server's own advice wins.** A ``Retry-After`` header (every OpenAI
   compatible endpoint we use sends one on 429) replaces the computed delay.
3. **Delays are fully jittered.** ``uniform(0, capped exponential)`` stops
   every session in the process from retrying in lockstep.
"""
import asyncio
import random

import structlog

from app.core.harness.config import RETRY

logger = structlog.get_logger()

#: Patch point for tests: retrying must not actually wait in a unit test.
_sleep = asyncio.sleep

RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})

#: Failures that are deterministic for this request or account.  Retrying
#: them burns a token budget and always fails the same way.
NON_RETRYABLE_MARKERS = (
    "insufficient_quota",
    "exceeded your current quota",
    "balance",
    "余额不足",
    "欠费",
    "context_length",
    "maximum context length",
    "invalid api key",
    "incorrect api key",
    "authentication",
    "unauthorized",
    "model_not_found",
    "does not exist",
)

_TRANSIENT_KEYWORDS = (
    "rate limit", "429", "503", "502", "504", "timeout",
    "throttl", "overloaded", "unavailable", "temporarily",
)


def http_status(exc: Exception) -> int | None:
    """HTTP status carried by a provider SDK exception, if any.

    The OpenAI SDK puts it on ``status_code`` and on ``response.status_code``;
    other clients only have one of the two.
    """
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    return status if isinstance(status, int) else None


def retry_after_seconds(exc: Exception) -> float | None:
    """``Retry-After`` in seconds, when the server sent a numeric one."""
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None) or getattr(exc, "headers", None)
    if not headers:
        return None
    try:
        raw = headers.get("retry-after") or headers.get("Retry-After")
    except AttributeError:
        return None
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


def _is_account_failure(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(marker in message for marker in NON_RETRYABLE_MARKERS)


def is_retryable_error(exc: Exception) -> bool:
    """True when waiting and trying again could plausibly succeed."""
    if _is_account_failure(exc):
        return False

    status = http_status(exc)
    if status is not None:
        return status in RETRYABLE_STATUS

    if isinstance(exc, (TimeoutError, ConnectionError, OSError, asyncio.TimeoutError)):
        return True

    message = str(exc).lower()
    return any(keyword in message for keyword in _TRANSIENT_KEYWORDS)


def backoff_delay(attempt: int, retry_after: float | None = None) -> float:
    """Seconds to wait before attempt ``attempt + 1``.

    ``Retry-After`` wins but is still clamped by ``max_delay`` so a server
    asking for an hour cannot pin a request open.
    """
    if retry_after is not None:
        return min(float(retry_after), RETRY.max_delay)
    ceiling = min(
        RETRY.max_delay,
        RETRY.base_delay * (RETRY.exponential_base ** attempt),
    )
    # Full jitter: uniform(0, ceiling).
    return random.uniform(0, ceiling)


def retry_delay_for(exc: Exception, attempt: int, max_retries: int) -> float | None:
    """Delay before the next attempt, or ``None`` when this error is final.

    Shared by :func:`retry_with_backoff` and callers that cannot hand their
    work to it — notably the agent loop, whose unit of work is a streaming
    async generator that must not be restarted once it has produced output.
    """
    if attempt >= max_retries or not is_retryable_error(exc):
        return None
    return backoff_delay(attempt, retry_after_seconds(exc))


async def sleep_before_retry(delay: float) -> None:
    """Wait between attempts.  Indirection exists so tests never really sleep."""
    await _sleep(delay)


async def retry_with_backoff(
    func, *args, context: str = "operation", max_retries: int | None = None, **kwargs
):
    """Execute ``func`` with jittered exponential backoff.

    ``max_retries`` overrides ``RETRY.max_retries`` for this call (attempts =
    ``max_retries + 1``).
    """
    attempts = RETRY.max_retries if max_retries is None else max(0, int(max_retries))
    last_exception: Exception | None = None
    for attempt in range(attempts + 1):
        try:
            return await func(*args, **kwargs)
        except Exception as e:  # noqa: BLE001 — re-raised below when final
            last_exception = e
            delay = retry_delay_for(e, attempt, attempts)
            if delay is None:
                break
            logger.warning(
                f"{context} failed (attempt {attempt + 1}), retrying in {delay:.1f}s",
                error=str(e), attempt=attempt + 1, status=http_status(e),
            )
            await _sleep(delay)

    assert last_exception is not None
    raise last_exception


async def with_timeout(coro, timeout: int, context: str = "operation"):
    """Enforce timeout on a coroutine."""
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        raise TimeoutError(f"{context} timed out after {timeout}s")

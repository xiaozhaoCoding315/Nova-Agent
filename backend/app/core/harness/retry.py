"""Exponential backoff retry with timeout enforcement."""
import asyncio
import time
import functools
import structlog
from app.core.harness.config import RETRY, TIMEOUTS

logger = structlog.get_logger()


def is_retryable_error(exc: Exception) -> bool:
    """Determine if an error is transient and worth retrying."""
    retryable = (
        TimeoutError, ConnectionError, OSError,
        asyncio.TimeoutError,
    )
    # Check by exception type
    if isinstance(exc, retryable):
        return True
    # Check by error message keywords
    msg = str(exc).lower()
    transient_keywords = ["rate limit", "429", "503", "502", "504",
                         "timeout", "throttl", "overloaded", "unavailable"]
    return any(kw in msg for kw in transient_keywords)


async def retry_with_backoff(func, *args, context: str = "operation", **kwargs):
    """Execute function with exponential backoff retry."""
    last_exception = None
    for attempt in range(RETRY.max_retries + 1):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            last_exception = e
            if attempt < RETRY.max_retries and is_retryable_error(e):
                delay = min(
                    RETRY.base_delay * (RETRY.exponential_base ** attempt),
                    RETRY.max_delay
                )
                logger.warning(f"{context} failed (attempt {attempt+1}), retrying in {delay:.1f}s",
                             error=str(e), attempt=attempt+1)
                await asyncio.sleep(delay)
            else:
                break

    raise last_exception


async def with_timeout(coro, timeout: int, context: str = "operation"):
    """Enforce timeout on a coroutine."""
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        raise TimeoutError(f"{context} timed out after {timeout}s")

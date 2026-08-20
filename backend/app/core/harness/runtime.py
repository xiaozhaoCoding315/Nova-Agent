"""Harness Runtime: unified execution wrapper with timeout + retry + circuit breaker + fallback."""
import asyncio
import structlog
from typing import Callable, Any, Optional
from app.core.harness.config import TIMEOUTS
from app.core.harness.retry import retry_with_backoff, with_timeout
from app.core.harness.circuit import get_breaker

logger = structlog.get_logger()


async def execute_with_harness(
    func: Callable,
    *args,
    context: str = "operation",
    timeout: int = None,
    use_retry: bool = True,
    use_circuit: bool = True,
    fallback: Callable = None,
    propagate: tuple = (),
    **kwargs
) -> Any:
    """
    Unified harness execution:
    1. Enforce timeout
    2. Retry with exponential backoff
    3. Circuit breaker protection
    4. Fallback on total failure

    ``propagate`` lists exception types that must surface to the caller with
    their original message (e.g. business validation errors) instead of being
    swallowed by the fallback.
    """
    breaker_name = context.replace(" ", "_")

    async def _wrapped():
        if use_circuit:
            breaker = get_breaker(breaker_name)
            return await breaker.call(func, *args, **kwargs)
        return await func(*args, **kwargs)

    async def _with_retry():
        if use_retry:
            return await retry_with_backoff(_wrapped, context=context)
        return await _wrapped()

    try:
        if timeout:
            return await with_timeout(_with_retry(), timeout=timeout, context=context)
        return await _with_retry()
    except Exception as e:
        if propagate and isinstance(e, propagate):
            raise
        logger.error(f"{context} failed completely", error=str(e))
        if fallback:
            logger.info(f"Using fallback for {context}")
            return await fallback(*args, **kwargs) if asyncio.iscoroutinefunction(fallback) else fallback(*args, **kwargs)
        raise


async def execute_parallel_with_fallback(tasks: list[dict], context: str = "parallel") -> list:
    """
    Execute multiple tasks in parallel, each with its own harness protection.
    tasks: [{"func": callable, "args": (), "kwargs": {}, "fallback": callable}]
    Returns list of results (or fallback values).
    """
    async def _run_task(task):
        try:
            return await execute_with_harness(
                task["func"],
                *task.get("args", ()),
                context=f"{context}/{task.get('name', 'task')}",
                timeout=task.get("timeout"),
                use_retry=task.get("use_retry", True),
                fallback=task.get("fallback"),
                **task.get("kwargs", {})
            )
        except Exception as e:
            logger.error(f"Task failed in {context}", error=str(e))
            return task.get("fallback_result")

    return await asyncio.gather(*[_run_task(t) for t in tasks])

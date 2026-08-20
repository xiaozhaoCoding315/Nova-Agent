import asyncio
import pytest
from app.core.harness.retry import is_retryable_error, retry_with_backoff, with_timeout
from app.core.harness.circuit import CircuitBreaker, CircuitState, get_breaker
from app.core.harness.runtime import execute_with_harness


def test_is_retryable_error():
    assert is_retryable_error(TimeoutError())
    assert is_retryable_error(ConnectionError())
    assert is_retryable_error(Exception("rate limit exceeded"))
    assert is_retryable_error(Exception("503 service unavailable"))
    assert not is_retryable_error(ValueError("bad input"))
    assert not is_retryable_error(KeyError("missing"))


@pytest.mark.asyncio
async def test_retry_with_backoff_success_first():
    call_count = 0
    async def succeeds():
        nonlocal call_count
        call_count += 1
        return "ok"
    result = await retry_with_backoff(succeeds, context="test")
    assert result == "ok"
    assert call_count == 1


@pytest.mark.asyncio
async def test_retry_with_backoff_eventual_success():
    call_count = 0
    async def fails_twice():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ConnectionError("transient")
        return "ok"
    result = await retry_with_backoff(fails_twice, context="test")
    assert result == "ok"
    assert call_count == 3


@pytest.mark.asyncio
async def test_retry_with_backoff_exhausts():
    async def always_fails():
        raise ConnectionError("persistent")
    with pytest.raises(ConnectionError):
        await retry_with_backoff(always_fails, context="test")


@pytest.mark.asyncio
async def test_with_timeout_success():
    async def fast():
        return "done"
    result = await with_timeout(fast(), timeout=5, context="test")
    assert result == "done"


@pytest.mark.asyncio
async def test_with_timeout_expires():
    async def slow():
        await asyncio.sleep(10)
        return "done"
    with pytest.raises(TimeoutError):
        await with_timeout(slow(), timeout=1, context="test")


def test_circuit_breaker_trips():
    import asyncio
    async def run():
        b = CircuitBreaker("test")
        b.config.failure_threshold = 3
        async def fails():
            raise ConnectionError("fail")
        for _ in range(3):
            try:
                await b.call(fails)
            except Exception:
                pass
        assert b.state == CircuitState.OPEN
    asyncio.run(run())


@pytest.mark.asyncio
async def test_execute_with_harness_success():
    async def works():
        return 42
    result = await execute_with_harness(works, context="test/timeout", timeout=5)
    assert result == 42


@pytest.mark.asyncio
async def test_execute_with_harness_fallback():
    async def fails():
        raise RuntimeError("broken")
    result = await execute_with_harness(
        fails, context="test/timeout", timeout=5,
        use_retry=False, fallback=lambda: "fallback_value"
    )
    assert result == "fallback_value"


@pytest.mark.asyncio
async def test_propagated_errors_do_not_trip_breaker():
    """Business validation errors (propagate) must not count as failures."""
    import app.core.harness.circuit as circuit_mod
    circuit_mod._breakers.pop("ut/nobreak", None)
    calls = 0

    async def rejecting():
        nonlocal calls
        calls += 1
        raise ValueError("invalid arguments")

    # more calls than the failure threshold (5)
    for _ in range(8):
        with pytest.raises(ValueError):
            await execute_with_harness(
                rejecting, context="ut/nobreak",
                propagate=(ValueError,), use_retry=False, fallback=None,
            )

    breaker = circuit_mod.get_breaker("ut/nobreak")
    assert breaker.state == CircuitState.CLOSED
    assert breaker.failure_count == 0
    assert calls == 8  # every call reached the handler

    circuit_mod._breakers.pop("ut/nobreak", None)

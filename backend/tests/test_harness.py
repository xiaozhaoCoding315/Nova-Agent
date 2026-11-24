import asyncio
import pytest
import app.core.harness.retry as retry_mod
from app.core.harness.retry import (
    backoff_delay,
    http_status,
    is_retryable_error,
    retry_after_seconds,
    retry_with_backoff,
    with_timeout,
)
from app.core.harness.circuit import CircuitBreaker, CircuitState
from app.core.harness.runtime import execute_with_harness


class FakeStatusError(Exception):
    """Duck-typed stand-in for openai.APIStatusError (no SDK import in tests)."""

    def __init__(self, status_code: int, message: str = "", headers: dict | None = None):
        super().__init__(message or f"status {status_code}")
        self.status_code = status_code
        self.response = type("Response", (), {"status_code": status_code,
                                              "headers": headers or {}})()


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    """Every retry test records delays instead of waiting for them."""
    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr(retry_mod, "_sleep", fake_sleep)
    return delays


def test_is_retryable_error():
    assert is_retryable_error(TimeoutError())
    assert is_retryable_error(ConnectionError())
    assert is_retryable_error(Exception("rate limit exceeded"))
    assert is_retryable_error(Exception("503 service unavailable"))
    assert not is_retryable_error(ValueError("bad input"))
    assert not is_retryable_error(KeyError("missing"))


def test_is_retryable_classifies_by_http_status():
    for status in (408, 425, 429, 500, 502, 503, 504):
        assert is_retryable_error(FakeStatusError(status)), status
    for status in (400, 401, 402, 403, 404, 413, 422):
        assert not is_retryable_error(FakeStatusError(status)), status


def test_http_status_reads_both_shapes():
    assert http_status(FakeStatusError(429)) == 429
    # openai.APIStatusError exposes the code on the response only in some paths
    exc = Exception("boom")
    exc.response = type("Response", (), {"status_code": 503})()
    assert http_status(exc) == 503
    assert http_status(ValueError("no status")) is None


def test_exhausted_quota_is_not_retryable():
    """A 429 caused by an empty account cannot recover by waiting."""
    assert not is_retryable_error(FakeStatusError(
        429, "insufficient_quota: You exceeded your current quota"))
    assert not is_retryable_error(Exception("账户余额不足，请充值"))
    assert not is_retryable_error(Exception("context_length_exceeded"))
    # A plain rate limit still is.
    assert is_retryable_error(FakeStatusError(429, "rate limit reached"))


def test_retry_after_seconds_parses_header():
    assert retry_after_seconds(FakeStatusError(429, headers={"retry-after": "2.5"})) == 2.5
    assert retry_after_seconds(FakeStatusError(429, headers={"retry-after": "oops"})) is None
    assert retry_after_seconds(FakeStatusError(429)) is None
    assert retry_after_seconds(ValueError("x")) is None


def test_backoff_is_jittered_and_capped(monkeypatch):
    monkeypatch.setattr(retry_mod.random, "uniform", lambda low, high: high)
    assert backoff_delay(0) == pytest.approx(retry_mod.RETRY.base_delay)
    assert backoff_delay(1) == pytest.approx(retry_mod.RETRY.base_delay * 2)
    # far beyond the cap: clamped to max_delay
    assert backoff_delay(20) == pytest.approx(retry_mod.RETRY.max_delay)

    monkeypatch.setattr(retry_mod.random, "uniform", lambda low, high: low)
    assert backoff_delay(3) == 0.0


def test_backoff_honours_retry_after_within_cap():
    assert backoff_delay(0, retry_after=7) == pytest.approx(7)
    assert backoff_delay(0, retry_after=10_000) == pytest.approx(retry_mod.RETRY.max_delay)


@pytest.mark.asyncio
async def test_retry_waits_for_retry_after(_no_real_sleep):
    calls = 0

    async def throttled():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise FakeStatusError(429, headers={"retry-after": "3"})
        return "ok"

    assert await retry_with_backoff(throttled, context="test") == "ok"
    assert _no_real_sleep == [3.0]


@pytest.mark.asyncio
async def test_retry_does_not_retry_deterministic_errors(_no_real_sleep):
    calls = 0

    async def unauthorized():
        nonlocal calls
        calls += 1
        raise FakeStatusError(401, "invalid api key")

    with pytest.raises(FakeStatusError):
        await retry_with_backoff(unauthorized, context="test")
    assert calls == 1
    assert _no_real_sleep == []


@pytest.mark.asyncio
async def test_retry_honours_max_retries_override(_no_real_sleep):
    calls = 0

    async def always_503():
        nonlocal calls
        calls += 1
        raise FakeStatusError(503)

    with pytest.raises(FakeStatusError):
        await retry_with_backoff(always_503, context="test", max_retries=1)
    assert calls == 2
    assert len(_no_real_sleep) == 1


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
    from app.core.harness.config import CircuitBreakerConfig

    async def run():
        # Own config: mutating the shared CIRCUIT object would leak into
        # every other breaker in the test session.
        b = CircuitBreaker("test", CircuitBreakerConfig(failure_threshold=3))

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
async def test_breaker_counts_one_failure_per_call_not_per_retry():
    """A retried attempt is not a new failure: 4 user actions = 4 failures."""
    import app.core.harness.circuit as circuit_mod
    from app.core.harness.config import CircuitBreakerConfig

    key = "ut/retry-count"
    circuit_mod._breakers.pop(key, None)

    async def always_fails():
        raise ConnectionError("down")

    for _ in range(4):
        with pytest.raises(ConnectionError):
            await execute_with_harness(
                always_fails, context=key, use_retry=True,
            )

    breaker = circuit_mod.get_breaker(key)
    assert breaker.failure_count == 4  # not 4 * (max_retries + 1)
    assert breaker.state == CircuitState.CLOSED
    assert isinstance(breaker.config, CircuitBreakerConfig)
    circuit_mod._breakers.pop(key, None)


@pytest.mark.asyncio
async def test_breaker_is_scoped_per_caller():
    """One user's failing sandbox must not lock everyone else out."""
    import app.core.harness.circuit as circuit_mod
    from app.core.harness.config import CircuitBreakerConfig

    async def fails():
        raise ConnectionError("down")

    async def works():
        return "ok"

    threshold_two = CircuitBreakerConfig(failure_threshold=2)
    circuit_mod.get_breaker("tool/run_command", "user-a").config = threshold_two
    circuit_mod.get_breaker("tool/run_command", "user-b").config = threshold_two
    try:
        for _ in range(2):
            with pytest.raises(ConnectionError):
                await execute_with_harness(
                    fails, context="tool/run_command", scope="user-a",
                    use_retry=False,
                )
        assert circuit_mod.get_breaker(
            "tool/run_command", "user-a").state == CircuitState.OPEN
        assert await execute_with_harness(
            works, context="tool/run_command", scope="user-b", use_retry=False,
        ) == "ok"
    finally:
        for scope in ("user-a", "user-b"):
            circuit_mod._breakers.pop(f"tool/run_command:{scope}", None)


@pytest.mark.asyncio
async def test_half_open_lets_only_one_probe_through():
    import time

    breaker = CircuitBreaker("ut/half-open")
    breaker.config.recovery_timeout = 0
    breaker.state = CircuitState.OPEN
    breaker.last_failure_time = time.time() - 1

    in_flight = 0
    max_in_flight = 0
    gate = asyncio.Event()

    async def slow_ok():
        nonlocal in_flight, max_in_flight
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        await gate.wait()
        in_flight -= 1
        return "ok"

    tasks = [asyncio.create_task(breaker.call(slow_ok)) for _ in range(4)]
    await asyncio.sleep(0.05)
    assert max_in_flight == 1, "half-open must admit a single probe"
    gate.set()
    results = await asyncio.gather(*tasks, return_exceptions=True)
    assert any(r == "ok" for r in results)
    assert max_in_flight == 1


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

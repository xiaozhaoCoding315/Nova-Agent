"""Circuit breaker pattern for external service calls.

Scope matters as much as the threshold: a breaker keyed only by tool name is
shared by every user in the process, so one user's broken sandbox would lock
the tool out for everybody.  Callers pass a ``scope`` (user id, provider id)
and the breaker lives at ``name:scope``.

A breaker records **one** outcome per user-visible call.  Retries inside a
call are the retry layer's business; counting each attempt here would trip a
five-failure breaker after roughly one failing operation.
"""
import asyncio
import time
from enum import Enum

from app.core.harness.config import CIRCUIT


class CircuitState(str, Enum):
    CLOSED = "closed"       # normal
    OPEN = "open"           # failing, reject calls
    HALF_OPEN = "half_open" # testing recovery


class CircuitOpenError(Exception):
    """Rejected because the breaker is open (or its probe slot is taken)."""


class CircuitBreaker:
    def __init__(self, name: str, config=None):
        self.name = name
        self.config = config or CIRCUIT
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time = 0.0
        self._lock = asyncio.Lock()
        # Half-open admits at most ``half_open_max_calls`` concurrent probes;
        # without the gate every queued request rushes the recovering service
        # at the same instant.
        self._probe_slots = asyncio.Semaphore(self.config.half_open_max_calls)

    def _refresh(self) -> None:
        """OPEN → HALF_OPEN once the recovery window has passed."""
        if (
            self.state == CircuitState.OPEN
            and time.time() - self.last_failure_time > self.config.recovery_timeout
        ):
            self.state = CircuitState.HALF_OPEN

    async def call(self, func, *args, ignore_exceptions: tuple = (), **kwargs):
        async with self._lock:
            self._refresh()
            state = self.state
        if state == CircuitState.OPEN:
            raise CircuitOpenError(f"Circuit breaker OPEN for {self.name}")

        probing = state == CircuitState.HALF_OPEN
        if probing and self._probe_slots.locked():
            # Another probe is still in flight; do not pile on.
            raise CircuitOpenError(f"Circuit breaker HALF_OPEN for {self.name}")
        if probing:
            await self._probe_slots.acquire()

        try:
            result = await func(*args, **kwargs)
        except Exception as e:
            # Business validation errors are not service failures: they must
            # not count toward tripping the breaker (e.g. an LLM repeatedly
            # sending invalid tool arguments is normal, not an outage).
            if ignore_exceptions and isinstance(e, ignore_exceptions):
                if probing:
                    self._probe_slots.release()
                raise
            async with self._lock:
                self.failure_count += 1
                self.last_failure_time = time.time()
                if self.failure_count >= self.config.failure_threshold:
                    self.state = CircuitState.OPEN
            if probing:
                self._probe_slots.release()
            raise

        async with self._lock:
            self.failure_count = 0
            self.state = CircuitState.CLOSED
        if probing:
            self._probe_slots.release()
        return result


# Global registry: ``name`` or ``name:scope`` → breaker.
_breakers: dict[str, CircuitBreaker] = {}


def breaker_key(name: str, scope: str | None = None) -> str:
    return f"{name}:{scope}" if scope else name


def get_breaker(name: str, scope: str | None = None) -> CircuitBreaker:
    key = breaker_key(name, scope)
    breaker = _breakers.get(key)
    if breaker is None:
        breaker = _breakers[key] = CircuitBreaker(key)
    return breaker

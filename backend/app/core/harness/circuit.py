"""Circuit breaker pattern for external service calls."""
import asyncio
import time
from enum import Enum
from app.core.harness.config import CIRCUIT


class CircuitState(str, Enum):
    CLOSED = "closed"       # normal
    OPEN = "open"           # failing, reject calls
    HALF_OPEN = "half_open" # testing recovery


class CircuitBreaker:
    def __init__(self, name: str, config=None):
        self.name = name
        self.config = config or CIRCUIT
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time = 0
        self._lock = asyncio.Lock()

    async def call(self, func, *args, **kwargs):
        async with self._lock:
            if self.state == CircuitState.OPEN:
                if time.time() - self.last_failure_time > self.config.recovery_timeout:
                    self.state = CircuitState.HALF_OPEN
                else:
                    raise Exception(f"Circuit breaker OPEN for {self.name}")

        try:
            result = await func(*args, **kwargs)
            async with self._lock:
                self.failure_count = 0
                self.state = CircuitState.CLOSED
            return result
        except Exception as e:
            async with self._lock:
                self.failure_count += 1
                self.last_failure_time = time.time()
                if self.failure_count >= self.config.failure_threshold:
                    self.state = CircuitState.OPEN
            raise


# Global registry
_breakers: dict[str, CircuitBreaker] = {}

def get_breaker(name: str) -> CircuitBreaker:
    if name not in _breakers:
        _breakers[name] = CircuitBreaker(name)
    return _breakers[name]

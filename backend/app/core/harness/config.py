"""Harness configuration: timeouts, retry policies, circuit breaker thresholds."""
from dataclasses import dataclass


@dataclass
class RetryConfig:
    max_retries: int = 3
    base_delay: float = 1.0        # seconds
    max_delay: float = 30.0        # cap
    exponential_base: float = 2.0
    retryable_exceptions: tuple = (TimeoutError, ConnectionError, OSError)


@dataclass
class TimeoutConfig:
    llm_timeout: int = 60          # LLM inference
    retrieval_timeout: int = 10    # RAG retrieval
    tool_timeout: int = 30         # External tool calls
    db_timeout: int = 5            # Database queries


@dataclass
class CircuitBreakerConfig:
    failure_threshold: int = 5      # trips after N failures
    recovery_timeout: int = 60      # seconds before half-open
    half_open_max_calls: int = 1    # test calls in half-open


TIMEOUTS = TimeoutConfig()
RETRY = RetryConfig()
CIRCUIT = CircuitBreakerConfig()

from fastapi import APIRouter
from app.core.harness.circuit import _breakers
from app.core.harness.config import TIMEOUTS, RETRY, CIRCUIT

router = APIRouter()


@router.get("/harness/status")
async def harness_status():
    """Return circuit breaker states and config."""
    breakers = {}
    for name, breaker in _breakers.items():
        breakers[name] = {
            "state": breaker.state.value,
            "failure_count": breaker.failure_count,
        }
    return {
        "circuit_breakers": breakers,
        "timeouts": {
            "llm": TIMEOUTS.llm_timeout,
            "retrieval": TIMEOUTS.retrieval_timeout,
            "tool": TIMEOUTS.tool_timeout,
            "db": TIMEOUTS.db_timeout,
        },
        "retry_policy": {
            "max_retries": RETRY.max_retries,
            "base_delay": RETRY.base_delay,
            "max_delay": RETRY.max_delay,
        },
    }

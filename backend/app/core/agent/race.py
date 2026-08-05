"""Race strategy for LLM provider selection.

Race multiple LLM providers in parallel and return the first successful result.
Useful for reducing latency by not waiting for slow/failing providers.
"""
import asyncio
import time
from enum import Enum
from typing import Any, Callable, Optional
from dataclasses import dataclass, field


class RaceStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    WON = "won"
    LOST = "lost"
    FAILED = "failed"


@dataclass
class RaceResult:
    provider_name: str
    status: RaceStatus = RaceStatus.PENDING
    tokens: list[str] = field(default_factory=list)
    error: Optional[str] = None
    start_time: float = 0.0
    end_time: float = 0.0
    latency_ms: float = 0.0


class RaceStrategy:
    """Race multiple LLM providers and stream from the first to respond.

    Strategy options:
    - "first_token": First provider to emit a token wins; losers are cancelled.
    """

    def __init__(
        self,
        providers: list,
        names: Optional[list[str]] = None,
        strategy: str = "first_token",
        timeout: Optional[float] = None,
    ):
        if not providers:
            raise ValueError("At least one provider required")
        self.providers = providers
        self.names = names or [f"provider_{i}" for i in range(len(providers))]
        self.strategy = strategy
        self.timeout = timeout
        self.winner: Optional[str] = None
        self.results: dict[str, RaceResult] = {}

    async def race(
        self,
        messages: list[dict],
    ) -> tuple[str, list[str]]:
        """Race providers, returning (winner_name, full_tokens)."""
        winner_box: dict[str, Optional[str]] = {"name": None}
        cancellation_event = asyncio.Event()
        self.results = {
            name: RaceResult(provider_name=name) for name in self.names
        }
        tasks: dict[str, asyncio.Task] = {}

        async def run_provider(name: str, provider):
            result = self.results[name]
            result.start_time = time.time()
            result.status = RaceStatus.RUNNING
            try:
                async for token in provider.astream(messages):
                    if cancellation_event.is_set() and winner_box["name"] != name:
                        result.status = RaceStatus.LOST
                        return

                    result.tokens.append(token)

                    # First token wins
                    if winner_box["name"] is None:
                        winner_box["name"] = name
                        self.winner = name
                        result.status = RaceStatus.WON
                        cancellation_event.set()

            except Exception as e:
                result.error = str(e)
                result.status = RaceStatus.FAILED
                return
            finally:
                if result.status == RaceStatus.RUNNING:
                    # Stream ended without error and without being cancelled
                    if result.tokens:
                        if winner_box["name"] is None:
                            winner_box["name"] = name
                            self.winner = name
                            result.status = RaceStatus.WON
                        else:
                            result.status = RaceStatus.LOST
                    else:
                        result.status = RaceStatus.FAILED
                        result.error = "empty response"
                result.end_time = time.time()
                result.latency_ms = (result.end_time - result.start_time) * 1000

        for name, provider in zip(self.names, self.providers):
            tasks[name] = asyncio.create_task(run_provider(name, provider))

        try:
            if self.timeout:
                await asyncio.wait_for(
                    asyncio.gather(*tasks.values(), return_exceptions=True),
                    timeout=self.timeout,
                )
            else:
                await asyncio.gather(*tasks.values(), return_exceptions=True)
        except asyncio.TimeoutError:
            cancellation_event.set()
            for r in self.results.values():
                if r.status == RaceStatus.RUNNING:
                    r.status = RaceStatus.FAILED
                    r.error = "timeout"

        # Cancel any still-running tasks
        for t in tasks.values():
            if not t.done():
                t.cancel()

        winner_name = winner_box["name"]
        if winner_name is None:
            errors = [f"{n}: {r.error}" for n, r in self.results.items() if r.error]
            raise RuntimeError(
                f"All race participants failed. Errors: {'; '.join(errors)}"
            )

        winner_result = self.results[winner_name]
        return winner_name, winner_result.tokens

    def get_race_stats(self) -> dict[str, Any]:
        return {
            "winner": self.winner,
            "strategy": self.strategy,
            "results": {
                name: {
                    "status": r.status.value,
                    "latency_ms": round(r.latency_ms, 1),
                    "token_count": len(r.tokens),
                    "error": r.error,
                }
                for name, r in self.results.items()
            },
        }

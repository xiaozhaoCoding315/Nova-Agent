import asyncio
import pytest
from app.core.agent.race import RaceStrategy, RaceStatus
from app.core.llm.base import LLMProvider


class FakeLLM(LLMProvider):
    def __init__(self, name, tokens=None, delay=0.0, should_fail=False):
        self._name = name
        self._tokens = tokens or [f"token_from_{name}"]
        self._delay = delay
        self._should_fail = should_fail

    async def astream(self, messages):
        if self._delay > 0:
            await asyncio.sleep(self._delay)
        if self._should_fail:
            raise RuntimeError(f"{self._name} failed")
        for token in self._tokens:
            yield token


@pytest.mark.asyncio
async def test_first_fast_provider_wins():
    fast = FakeLLM("fast", tokens=["fast_token"], delay=0.01)
    slow = FakeLLM("slow", tokens=["slow_token"], delay=0.1)

    race = RaceStrategy(providers=[slow, fast], names=["slow", "fast"])
    winner, tokens = await race.race([{"role": "user", "content": "hi"}])

    assert winner == "fast"
    assert tokens == ["fast_token"]


@pytest.mark.asyncio
async def test_fallback_when_first_fails():
    failing = FakeLLM("bad", should_fail=True)
    good = FakeLLM("good", tokens=["good_token"], delay=0.01)

    race = RaceStrategy(providers=[failing, good], names=["bad", "good"])
    winner, tokens = await race.race([{"role": "user", "content": "hi"}])

    assert winner == "good"
    assert tokens == ["good_token"]


@pytest.mark.asyncio
async def test_all_fail_raises():
    failing1 = FakeLLM("bad1", should_fail=True)
    failing2 = FakeLLM("bad2", should_fail=True)

    race = RaceStrategy(providers=[failing1, failing2], names=["bad1", "bad2"])
    with pytest.raises(RuntimeError, match="All race participants failed"):
        await race.race([{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
async def test_single_provider():
    only = FakeLLM("only", tokens=["only_token"])
    race = RaceStrategy(providers=[only], names=["only"])
    winner, tokens = await race.race([{"role": "user", "content": "hi"}])

    assert winner == "only"
    assert tokens == ["only_token"]


@pytest.mark.asyncio
async def test_empty_providers_raises():
    with pytest.raises(ValueError, match="At least one"):
        RaceStrategy(providers=[])


@pytest.mark.asyncio
async def test_race_stats():
    fast = FakeLLM("fast", tokens=["a", "b"], delay=0.01)
    slow = FakeLLM("slow", tokens=["x"], delay=0.05)

    race = RaceStrategy(providers=[fast, slow], names=["fast", "slow"])
    await race.race([{"role": "user", "content": "hi"}])

    stats = race.get_race_stats()
    assert stats["winner"] == "fast"
    assert "fast" in stats["results"]
    assert "slow" in stats["results"]

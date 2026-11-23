"""Provider clients are shared per (loop, endpoint, key) and closed at shutdown.

Before this, every round of every turn built a new ``AsyncOpenAI`` with its own
``httpx`` pool and never closed any of them: a 16-round turn leaked 16 pools,
which is real memory pressure on a 2G host.
"""
import asyncio

import pytest

from app.core.llm import client_cache
from app.core.llm.factory import OpenAICompatibleLLM


@pytest.fixture(autouse=True)
def _clean_cache():
    client_cache._clients.clear()
    yield
    client_cache._clients.clear()


def test_same_endpoint_and_key_share_one_client():
    first = OpenAICompatibleLLM("key-a", "https://api.example.com/v1", "model-1")
    second = OpenAICompatibleLLM("key-a", "https://api.example.com/v1", "model-2")

    assert first.client is second.client
    assert client_cache.cached_client_count() == 1


def test_different_keys_get_different_clients():
    first = OpenAICompatibleLLM("key-a", "https://api.example.com/v1", "m")
    second = OpenAICompatibleLLM("key-b", "https://api.example.com/v1", "m")

    assert first.client is not second.client
    assert client_cache.cached_client_count() == 2


def test_trailing_slash_does_not_split_the_cache():
    first = OpenAICompatibleLLM("key-a", "https://api.example.com/v1", "m")
    second = OpenAICompatibleLLM("key-a", "https://api.example.com/v1/", "m")

    assert first.client is second.client


def test_cache_key_never_contains_the_raw_key():
    OpenAICompatibleLLM("sk-secret-value", "https://api.example.com/v1", "m")
    for key in client_cache._clients:
        assert "sk-secret-value" not in "".join(str(part) for part in key)


@pytest.mark.asyncio
async def test_close_clients_closes_and_empties_the_cache():
    llm = OpenAICompatibleLLM("key-a", "https://api.example.com/v1", "m")
    assert not llm.client.is_closed()

    await client_cache.close_clients()

    assert llm.client.is_closed()
    assert client_cache.cached_client_count() == 0


@pytest.mark.asyncio
async def test_a_closed_client_is_not_handed_out_again():
    first = OpenAICompatibleLLM("key-a", "https://api.example.com/v1", "m")
    await first.client.close()

    second = OpenAICompatibleLLM("key-a", "https://api.example.com/v1", "m")

    assert second.client is not first.client
    assert not second.client.is_closed()


def test_a_client_from_a_closed_loop_is_not_reused():
    """A pool's sockets belong to the loop that opened them."""
    async def _build():
        return OpenAICompatibleLLM("key-a", "https://api.example.com/v1", "m")

    first = asyncio.run(_build())
    asyncio.run(first.client.close())
    # The loop the first client was built on is gone; handing it back would
    # raise "Event loop is closed" on the first request.
    second = asyncio.run(_build())

    assert second.client is not first.client
    asyncio.run(second.client.close())

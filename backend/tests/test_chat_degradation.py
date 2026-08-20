import json
import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch
from app.main import app


@pytest.mark.asyncio
async def test_assemble_context_survives_memory_failure():
    from app.core.memory.context_assembler import assemble_context

    async def boom(*args, **kwargs):
        raise RuntimeError("PG down")

    # assemble_context 在函数内部 import 这三个名字，因此 patch 源模块即可生效
    with patch("app.core.memory.session.get_history", new=boom), \
         patch("app.core.memory.store.get_facts", new=boom), \
         patch("app.core.memory.graph_memory.search_graph_memory", new=boom):
        ctx = await assemble_context("问题", "any-session")
    assert ctx == "（无历史记忆）"


def test_chat_stream_survives_memory_write_failure():
    async def fake_retrieve(q, top_k=5):
        return []

    class FakePlainLLM:
        async def astream_with_tools(self, messages, tools):
            yield {"type": "content", "content": "hi"}
            yield {"type": "finish", "finish_reason": "stop"}

    async def fake_memory(*args, **kwargs):
        return ""

    async def failing_write(*args, **kwargs):
        raise RuntimeError("PG down")

    with patch("app.api.v1.chat.retrieve", new=fake_retrieve), \
         patch("app.api.v1.chat.get_llm", return_value=FakePlainLLM()), \
         patch("app.api.v1.chat.add_message", new=failing_write), \
         patch("app.api.v1.chat.assemble_context", new=fake_memory), \
         patch("app.api.v1.chat.check_should_archive", new=AsyncMock(return_value=False)):
        with TestClient(app).stream(
            "POST", "/api/v1/chat/message",
            json={"message": "hi", "session_id": "deg-test-1"},
        ) as resp:
            assert resp.status_code == 200
            body = b"".join(resp.iter_bytes())
            assert b'"type": "done"' in body

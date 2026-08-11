import json
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch
from app.main import app


def test_chat_returns_sse_stream():
    mock_token = "FastAPI中间件通过@app.middleware装饰器实现"

    async def fake_retrieve(q, top_k=5):
        return []

    async def fake_stream(messages):
        yield mock_token

    async def fake_memory(*args, **kwargs):
        return ""

    with patch("app.api.v1.chat.retrieve", new=fake_retrieve), \
         patch("app.api.v1.chat.get_llm") as mock_llm, \
         patch("app.api.v1.chat.add_message", new=AsyncMock()), \
         patch("app.api.v1.chat.assemble_context", new=fake_memory), \
         patch("app.api.v1.chat.check_should_archive", new=AsyncMock(return_value=False)):
        mock_llm.return_value.astream = fake_stream
        with TestClient(app).stream(
            "POST", "/api/v1/chat/message",
            json={"message": "FastAPI中间件"},
        ) as resp:
            assert resp.status_code == 200
            body = b""
            for chunk in resp.iter_bytes():
                body += chunk
            assert b"FastAPI" in body

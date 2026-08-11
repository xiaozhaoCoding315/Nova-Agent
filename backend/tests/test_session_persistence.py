import uuid
import pytest
from app.core.memory.session import (
    get_or_create_session,
    add_message,
    get_history,
    get_summary,
    clear_session,
)


@pytest.mark.asyncio
async def test_add_and_read_message():
    sid = f"ses-{uuid.uuid4().hex[:8]}"
    await add_message(sid, "user", "我喜欢FastAPI")
    history = await get_history(sid, last_n=10)
    assert history and history[0]["role"] == "user"
    assert history[0]["content"] == "我喜欢FastAPI"


@pytest.mark.asyncio
async def test_history_is_chronological():
    sid = f"ses-{uuid.uuid4().hex[:8]}"
    await add_message(sid, "user", "你好")
    await add_message(sid, "assistant", "我是Nova")
    history = await get_history(sid, last_n=10)
    assert [m["role"] for m in history] == ["user", "assistant"]


@pytest.mark.asyncio
async def test_summary_counts_messages():
    sid = f"ses-{uuid.uuid4().hex[:8]}"
    await add_message(sid, "user", "a")
    await add_message(sid, "assistant", "b")
    summary = await get_summary(sid)
    assert summary["message_count"] == 2
    assert summary["session_id"] == sid


@pytest.mark.asyncio
async def test_clear_session_removes_messages():
    sid = f"ses-{uuid.uuid4().hex[:8]}"
    await add_message(sid, "user", "x")
    await clear_session(sid)
    assert await get_history(sid, last_n=10) == []

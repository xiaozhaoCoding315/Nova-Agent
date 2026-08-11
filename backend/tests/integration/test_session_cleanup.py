import uuid
import pytest
from app.core.memory.session import add_message
from app.core.memory.store import run_session_cleanup


@pytest.mark.asyncio
@pytest.mark.integration
async def test_session_cleanup_deletes_old_messages():
    sid = f"ses-old-{uuid.uuid4().hex[:6]}"
    await add_message(sid, "user", "老消息")
    # 把这条消息时间戳改到 31 天前
    from app.db import execute
    await execute(
        "UPDATE chat_messages SET created_at = now() - interval '31 days' WHERE session_id = %s",
        (sid,),
    )
    deleted = await run_session_cleanup(ttl_days=30)
    assert deleted >= 1
    from app.core.memory.session import get_history
    assert await get_history(sid) == []

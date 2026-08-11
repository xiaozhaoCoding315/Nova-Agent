import pytest
from app.core.memory.context_assembler import assemble_context
from app.core.memory.store import save_fact
from app.core.memory.session import add_message

@pytest.mark.asyncio
@pytest.mark.integration
async def test_four_layer_memory_assembly():
    sid = "integration-mem-test"
    await add_message(sid, "user", "我喜欢FastAPI")
    await save_fact(sid, "用户偏好FastAPI", "preference", 0.8)
    ctx = await assemble_context("Web框架推荐", sid)
    assert len(ctx) > 0

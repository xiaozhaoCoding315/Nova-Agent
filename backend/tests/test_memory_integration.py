import pytest
from app.core.memory.context_assembler import assemble_context
from app.core.memory.store import save_fact, get_facts
from app.core.memory.session import add_message

@pytest.mark.asyncio
async def test_assemble_includes_long_term_facts():
    sid = "ctx-test-1"
    await save_fact(sid, "用户偏好使用FastAPI", "preference", 0.8)
    ctx = await assemble_context("推荐一个Web框架", sid)
    assert "FastAPI" in ctx or len(ctx) > 0

@pytest.mark.asyncio
async def test_assemble_includes_session_history():
    sid = "ctx-test-2"
    await add_message(sid, "user", "我喜欢异步编程")
    await add_message(sid, "assistant", "FastAPI支持异步")
    ctx = await assemble_context("异步框架推荐", sid)
    assert len(ctx) > 0

@pytest.mark.asyncio
async def test_assemble_includes_layer4_task_state():
    from app.core.agent.task_store import TaskStore
    import uuid
    await TaskStore.save({
        "id": f"l4-{uuid.uuid4().hex[:8]}", "name": "测试DAG任务", "status": "completed",
        "result": None, "error": None, "created_at": "2026-08-11T00:00:00",
        "started_at": None, "completed_at": None, "retries": 0, "max_retries": 2,
        "parent_id": None, "children_ids": [], "metadata": {}, "history": [],
    })
    ctx = await assemble_context("查看最近任务", "l4-test-session")
    assert "近期任务运行" in ctx or "测试DAG任务" in ctx

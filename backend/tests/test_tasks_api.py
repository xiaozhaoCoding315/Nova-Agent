import asyncio
import json
import re
from fastapi.testclient import TestClient
from app.main import app
from app.core.agent.task_store import TaskStore
from unittest.mock import patch


def test_get_task_returns_404_for_missing():
    with TestClient(app) as client:
        resp = client.get("/api/v1/tasks/does-not-exist")
    assert resp.status_code == 404


def test_execute_persists_task_run():
    async def fake_decompose(task):
        return {
            "nodes": [{"id": "node_1", "name": "调研", "task_type": "research", "action": "调研", "depends_on": []}],
            "summary": "测试",
        }

    async def fake_stream(messages):
        yield "结果"

    # execute_node_action 在函数体内 from app.core.llm.factory import get_llm，
    # 因此 patch 源模块的 get_llm 才会生效（不能 patch app.api.v1.tasks.get_llm）。
    mock_llm = patch("app.core.llm.factory.get_llm").start()
    mock_llm.return_value.astream = fake_stream
    try:
        with patch("app.api.v1.tasks.decompose_task", new=fake_decompose), \
                TestClient(app) as client:
            with client.stream("POST", "/api/v1/tasks/execute", json={"task": "测试任务"}) as resp:
                body = b"".join(resp.iter_bytes()).decode("utf-8", errors="replace")
    finally:
        mock_llm.stop()

    assert '"type": "done"' in body
    # 提取 task_id（取最后一条 done 事件）
    ids = re.findall(r'"task_id":\s*"([^"]+)"', body)
    assert ids, "expected task_id in SSE events"
    tid = None
    for line in body.split("\n\n"):
        if '"type": "done"' in line and line.startswith("data: "):
            tid = json.loads(line[6:])["task_id"]
    assert tid

    # 验证持久化：_persist 是 fire-and-forget 后台写库，轮询等待其完成（约 2s 上限）。
    async def _poll():
        for _ in range(20):
            saved = await TaskStore.get(tid)
            if saved is not None:
                return saved
            await asyncio.sleep(0.1)
        return None

    saved = asyncio.run(_poll())
    assert saved is not None, "task run was not persisted"
    assert saved["name"] == "测试任务"

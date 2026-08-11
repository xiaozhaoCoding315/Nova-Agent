import uuid
from fastapi.testclient import TestClient
from app.main import app
from app.core.agent.task_store import TaskStore
from app.core.agent.decomposer import decompose_task
from unittest.mock import AsyncMock, patch


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

    with patch("app.api.v1.tasks.decompose_task", new=fake_decompose), \
         patch("app.api.v1.tasks.get_llm") as mock_llm:
        # execute_node_action 内部会调 get_llm 流式
        async def fake_stream(messages):
            yield "结果"

        mock_llm.return_value.astream = fake_stream

        with TestClient(app) as client:
            with client.stream("POST", "/api/v1/tasks/execute", json={"task": "测试任务"}) as resp:
                body = b"".join(resp.iter_bytes()).decode("utf-8", errors="replace")

    assert '"type": "done"' in body
    # 提取 task_id 并验证已持久化
    import re, json
    ids = re.findall(r'"task_id":\s*"([^"]+)"', body)
    assert ids, "expected task_id in SSE events"
    # 从最后一条 done 事件取 id
    for line in body.split("\n\n"):
        if '"type": "done"' in line and line.startswith("data: "):
            evt = json.loads(line[6:])
            tid = evt["task_id"]
    # 直接查 store（异步）——用运行 loop 执行
    import asyncio
    saved = asyncio.run(TaskStore.get(tid))
    assert saved is not None
    assert saved["name"] == "测试任务"

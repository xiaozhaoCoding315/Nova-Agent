import asyncio
import json
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from app.core.agent.decomposer import decompose_task, execute_node_action
from app.core.agent.dag import DAGWorkflow, DAGNode

router = APIRouter()


@router.post("/tasks/execute")
async def execute_task(request: dict):
    """Execute a complex task as a DAG with streaming progress."""
    task_description = request.get("task", "")
    if not task_description:
        return {"error": "No task provided"}

    async def event_stream():
        # Step 1: Decompose
        yield f"data: {json.dumps({'type': 'decomposing', 'message': '正在拆解任务...'}, ensure_ascii=False)}\n\n"

        dag_def = await decompose_task(task_description)

        yield f"data: {json.dumps({'type': 'dag_ready', 'nodes': dag_def['nodes'], 'summary': dag_def.get('summary', '')}, ensure_ascii=False)}\n\n"

        # Step 2: Execute nodes in topological order with parallelism
        workflow = DAGWorkflow(name=task_description[:50])
        for node_def in dag_def["nodes"]:
            workflow.add_node(
                DAGNode(
                    id=node_def["id"],
                    name=node_def["name"],
                    func=execute_node_action,
                    args=(node_def,),
                    dependencies=node_def.get("depends_on", []),
                )
            )

        async for event in workflow.execute_race_streaming():
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

        # Step 3: Done
        yield f"data: {json.dumps({'type': 'done', 'task': task_description}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
    )


@router.post("/tasks/decompose")
async def decompose_only(request: dict):
    """Only decompose a task, don't execute. Returns the DAG structure."""
    task_description = request.get("task", "")
    if not task_description:
        return {"error": "No task provided"}

    dag_def = await decompose_task(task_description)
    return dag_def

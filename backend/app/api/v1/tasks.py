import asyncio
import json
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from app.core.agent.decomposer import decompose_task, execute_node_action
from app.core.agent.dag import DAGWorkflow, DAGNode
from app.core.agent.state import TaskStateManager
from app.core.agent.task_store import TaskStore

router = APIRouter()


@router.post("/tasks/execute")
async def execute_task(request: dict):
    """Execute a complex task as a DAG with streaming progress + persisted run."""
    task_description = request.get("task", "")
    if not task_description:
        return {"error": "No task provided"}

    mgr = TaskStateManager()
    run = mgr.create_task(name=task_description[:50], metadata={"type": "dag_run"})
    mgr.start_task(run.id)

    async def event_stream():
        # Step 1: Decompose
        yield f"data: {json.dumps({'type': 'decomposing', 'message': '正在拆解任务...', 'task_id': run.id}, ensure_ascii=False)}\n\n"

        try:
            dag_def = await decompose_task(task_description)
        except Exception as e:
            mgr.fail_task(run.id, error=f"decompose failed: {e}")
            yield f"data: {json.dumps({'type': 'node_failed', 'error': str(e)}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'task': task_description, 'task_id': run.id}, ensure_ascii=False)}\n\n"
            return

        yield f"data: {json.dumps({'type': 'dag_ready', 'nodes': dag_def['nodes'], 'summary': dag_def.get('summary', ''), 'task_id': run.id}, ensure_ascii=False)}\n\n"

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

        try:
            async for event in workflow.execute_race_streaming():
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            mgr.complete_task(run.id, result={"dag": dag_def})
        except Exception as e:
            mgr.fail_task(run.id, error=str(e))

        # Step 3: Done
        yield f"data: {json.dumps({'type': 'done', 'task': task_description, 'task_id': run.id}, ensure_ascii=False)}\n\n"

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


@router.get("/tasks/{task_id}")
async def get_task(task_id: str):
    """Get a persisted task run's lifecycle state (Layer 4)."""
    task = await TaskStore.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task

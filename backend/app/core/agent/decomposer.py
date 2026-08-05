"""LLM-powered task decomposition: turn complex requests into executable DAGs."""
import json
import structlog
from app.core.agent.dag import DAGWorkflow, DAGNode
from app.core.llm.factory import get_llm

logger = structlog.get_logger()

DECOMPOSE_PROMPT = """将以下复杂技术任务拆解为DAG（有向无环图）节点。
返回JSON格式：
```json
{{
  "nodes": [
    {{"id": "node_1", "name": "任务描述", "task_type": "search|code|research|write|review", "action": "具体执行指令"}},
    {{"id": "node_2", "name": "对比分析", "task_type": "review", "action": "对比node_1和已有信息", "depends_on": ["node_1"]}}
  ],
  "summary": "任务概述"
}}
```

规则：
- 每个节点有唯一id、name、task_type、action
- 有依赖的节点加 depends_on 字段（值为依赖节点的id列表）
- task_type可选：search(搜索查询), research(技术调研), code(代码实现), write(文档编写), review(对比分析), execute(执行命令)
- 节点数量2-6个，不宜过多
- 确保无循环依赖

用户任务：{task}
"""


async def decompose_task(task_description: str) -> dict:
    """Use LLM to decompose a complex task into a DAG structure."""
    prompt = DECOMPOSE_PROMPT.format(task=task_description)

    full_response = ""
    try:
        llm = get_llm()
        async for token in llm.astream([{"role": "user", "content": prompt}]):
            full_response += token
    except Exception as e:
        logger.error(f"Task decomposition failed: {e}")
        # Fallback: single node
        return {
            "nodes": [{"id": "node_1", "name": task_description, "task_type": "research", "action": task_description}],
            "summary": task_description,
        }

    # Parse JSON from response
    try:
        import re
        # Find JSON block
        match = re.search(r'\{[\s\S]*\}', full_response)
        if match:
            data = json.loads(match.group())
            # Validate structure
            if "nodes" in data and isinstance(data["nodes"], list) and len(data["nodes"]) > 0:
                # Ensure all nodes have required fields
                for i, node in enumerate(data["nodes"]):
                    if "id" not in node:
                        node["id"] = f"node_{i+1}"
                    if "name" not in node:
                        node["name"] = f"Step {i+1}"
                    if "task_type" not in node:
                        node["task_type"] = "research"
                    if "action" not in node:
                        node["action"] = node["name"]
                    if "depends_on" not in node:
                        node["depends_on"] = []
                return data
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning(f"Failed to parse decomposition JSON: {e}")

    # Fallback
    return {
        "nodes": [{"id": "node_1", "name": task_description, "task_type": "research", "action": task_description}],
        "summary": task_description,
    }


async def execute_node_action(node: dict) -> dict:
    """Execute a single DAG node's action using RAG + LLM."""
    from app.core.rag.retriever import retrieve
    from app.core.llm.factory import get_llm

    task_type = node.get("task_type", "research")
    action = node.get("action", "")

    # Retrieve context
    chunks = []
    try:
        chunks = await retrieve(action, top_k=5)
    except Exception:
        pass

    context = "\n---\n".join(c.content for c in chunks) if chunks else ""

    if task_type == "search":
        # Search and summarize
        system = "你是一个技术搜索助手。基于以下上下文回答问题。"
        msgs = [
            {"role": "system", "content": f"{system}\n\n## 上下文\n{context}"},
            {"role": "user", "content": action},
        ]
    elif task_type == "research":
        # Research with deep context
        system = "你是一个技术研究员。基于以下上下文进行深度调研分析。"
        msgs = [
            {"role": "system", "content": f"{system}\n\n## 上下文\n{context}"},
            {"role": "user", "content": action},
        ]
    elif task_type == "write":
        system = "你是一个技术文档撰写专家。基于以下上下文撰写文档。"
        msgs = [
            {"role": "system", "content": f"{system}\n\n## 上下文\n{context}"},
            {"role": "user", "content": action},
        ]
    elif task_type == "review":
        system = "你是一个技术分析师。基于以下上下文进行对比分析。"
        msgs = [
            {"role": "system", "content": f"{system}\n\n## 上下文\n{context}"},
            {"role": "user", "content": action},
        ]
    else:
        system = "你是一个技术助手。"
        msgs = [
            {"role": "system", "content": f"{system}\n\n## 上下文\n{context}"},
            {"role": "user", "content": action},
        ]

    result_text = ""
    try:
        llm = get_llm()
        async for token in llm.astream(msgs):
            result_text += token
    except Exception as e:
        result_text = f"[执行错误: {e}]"

    return {
        "node_id": node.get("id"),
        "node_name": node.get("name"),
        "task_type": task_type,
        "result": result_text,
        "chunks_used": len(chunks),
    }


async def execute_dag_task(task_description: str) -> dict:
    """Full pipeline: decompose → build DAG → execute → return results."""
    # Step 1: Decompose
    dag_def = await decompose_task(task_description)

    # Step 2: Build DAG
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

    # Step 3: Execute with parallel batch execution
    results = await workflow.execute()

    return {
        "task": task_description,
        "summary": dag_def.get("summary", ""),
        "dag": dag_def,
        "results": {nid: node.result for nid, node in results.items() if node.status.value == "completed"},
        "status": "completed",
    }

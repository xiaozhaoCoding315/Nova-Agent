"""update_plan tool: a lightweight, user-visible todo list for long tasks."""
from app.core.tools.base import ToolBusinessError, ToolContext, ToolDefinition

MAX_STEPS = 12
STATUSES = {"pending", "in_progress", "completed"}


async def update_plan(args: dict, ctx: ToolContext) -> dict:
    steps = args.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ToolBusinessError("steps 必须是非空数组")
    if len(steps) > MAX_STEPS:
        raise ToolBusinessError(f"计划最多 {MAX_STEPS} 步，请合并相近步骤")

    clean: list[dict] = []
    for index, item in enumerate(steps, 1):
        if not isinstance(item, dict):
            raise ToolBusinessError(f"第 {index} 步格式不正确")
        title = str(item.get("title") or "").strip()[:200]
        status = str(item.get("status") or "pending")
        if not title:
            raise ToolBusinessError(f"第 {index} 步缺少 title")
        if status not in STATUSES:
            raise ToolBusinessError(
                f"第 {index} 步 status 必须是 pending / in_progress / completed"
            )
        clean.append({"title": title, "status": status})

    if sum(1 for step in clean if step["status"] == "in_progress") > 1:
        raise ToolBusinessError("同一时间只能有一个 in_progress 步骤")

    explanation = str(args.get("explanation") or "").strip()[:500]
    return {"steps": clean, "explanation": explanation, "count": len(clean)}


TOOL = ToolDefinition(
    name="update_plan",
    description=(
        "维护当前任务的可见执行计划（待办清单）。多步骤任务开始时先建立计划，"
        "执行过程中更新每一步状态；步骤控制在 12 个以内，同一时间只有一个 in_progress。"
        "这只是进度展示，不会替代真实工具执行。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "steps": {
                "type": "array",
                "description": "计划步骤（按执行顺序）",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "步骤标题"},
                        "status": {
                            "type": "string",
                            "enum": ["pending", "in_progress", "completed"],
                        },
                    },
                    "required": ["title", "status"],
                },
            },
            "explanation": {"type": "string", "description": "可选的计划说明"},
        },
        "required": ["steps"],
    },
    func=update_plan,
    category="read",
    capabilities=[],
    timeout=5,
)

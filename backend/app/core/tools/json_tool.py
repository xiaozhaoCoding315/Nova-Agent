"""JSON skill: validate / format / extract — high-frequency developer chores."""
import json

from app.core.tools.base import Tool, ToolError

_MAX_INPUT_CHARS = 20000


def _walk(obj, path: str):
    """Yield (dotted_path, value) for every node."""
    yield path, obj
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk(v, f"{path}.{k}" if path else str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk(v, f"{path}[{i}]")


async def process_json(data: str, operation: str = "validate", query: str = "") -> dict:
    """Tool handler: validate / format / query a JSON payload."""
    if not data or not data.strip():
        raise ToolError("empty json")
    if len(data) > _MAX_INPUT_CHARS:
        raise ToolError(f"json too long (max {_MAX_INPUT_CHARS} chars)")

    try:
        parsed = json.loads(data)
    except json.JSONDecodeError as exc:
        return {
            "ok": True,  # 工具本身执行成功，校验结果是"非法"
            "valid": False,
            "operation": operation,
            "error": f"第 {exc.lineno} 行第 {exc.colno} 列: {exc.msg}",
        }

    if operation == "format":
        formatted = json.dumps(parsed, ensure_ascii=False, indent=2)
        return {"valid": True, "operation": "format",
                "formatted": formatted[:5000], "truncated": len(formatted) > 5000}

    if operation == "extract":
        if not query:
            raise ToolError("extract 操作需要 query 参数（点号路径，如 data.items[0].id）")
        current = parsed
        # 支持 "a.b[0].c" 风格路径
        for part in query.replace("[", ".[").split("."):
            if not part:
                continue
            try:
                if part.startswith("["):
                    current = current[int(part.strip("[]"))]
                else:
                    current = current[part]
            except (KeyError, IndexError, TypeError, ValueError):
                return {"valid": True, "operation": "extract", "found": False, "query": query}
        return {
            "valid": True, "operation": "extract", "found": True, "query": query,
            "value": current if not isinstance(current, (dict, list))
                     else json.dumps(current, ensure_ascii=False)[:2000],
        }

    # 默认 validate：返回结构概览
    keys = [p for p, _v in _walk(parsed, "") if p and p.count(".") <= 1][:20]
    return {
        "valid": True, "operation": "validate",
        "top_type": type(parsed).__name__,
        "top_keys": list(parsed.keys())[:15] if isinstance(parsed, dict) else None,
        "size_chars": len(data),
        "paths_preview": keys,
    }


json_tool = Tool(
    name="json_tool",
    description=(
        "JSON 处理工具。三种操作：validate 校验合法性并返回结构概览；"
        "format 格式化缩进；extract 按点号路径提取字段值。"
        "当用户需要校验/格式化 JSON、从大 JSON 里取值时调用，"
        "比在回答里手写更可靠。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "data": {"type": "string", "description": "JSON 原文"},
            "operation": {
                "type": "string",
                "enum": ["validate", "format", "extract"],
                "description": "操作类型，默认 validate",
            },
            "query": {
                "type": "string",
                "description": "extract 时的字段路径，如 data.items[0].id",
            },
        },
        "required": ["data"],
    },
    handler=process_json,
)

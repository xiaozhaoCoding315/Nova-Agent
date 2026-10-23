"""json_tool: validate / format / extract / convert JSON and YAML."""
import json
import re

import yaml

from app.core.tools.base import ToolBusinessError, ToolContext, ToolDefinition

_PATH_TOKEN = re.compile(r"([^.\[\]]+)|\[(\d+)\]")


def _parse(text: str, fmt: str = "auto") -> tuple[object, str]:
    text = text.strip()
    if fmt in ("json", "auto"):
        try:
            return json.loads(text), "json"
        except json.JSONDecodeError as exc:
            if fmt == "json":
                raise ToolBusinessError(f"JSON 解析失败：第 {exc.lineno} 行第 {exc.colno} 列：{exc.msg}")
    try:
        return yaml.safe_load(text), "yaml"
    except yaml.YAMLError as exc:
        raise ToolBusinessError(f"YAML 解析失败：{str(exc)[:200]}")


def _walk(obj: object, path: str) -> object:
    current = obj
    for name, index in _PATH_TOKEN.findall(path):
        try:
            current = current[name] if name else current[int(index)]
        except (KeyError, IndexError, TypeError):
            raise ToolBusinessError(f"路径不存在：{path}（在 '{name or index}' 处中断）")
    return current


def _describe(obj: object, depth: int = 0) -> object:
    if isinstance(obj, dict):
        return {k: _describe(v, depth + 1) for k, v in list(obj.items())[:20]}
    if isinstance(obj, list):
        return [f"<{len(obj)} items>"] if obj and depth > 0 else [_describe(v, depth + 1) for v in obj[:5]]
    return obj


async def json_tool(args: dict, ctx: ToolContext) -> dict:
    text = args.get("input") or ""
    if not text.strip():
        raise ToolBusinessError("input 不能为空")
    mode = args.get("mode", "validate")
    fmt = args.get("format", "auto")

    data, detected = _parse(text, fmt)

    if mode == "validate":
        errors = []
        if detected == "json":
            pass  # parsed successfully
        return {
            "valid": True,
            "format": detected,
            "root_type": type(data).__name__,
            "summary": _describe(data),
            "errors": errors,
        }

    if mode == "format":
        if detected == "json" or args.get("to") == "json":
            return {"formatted": json.dumps(data, ensure_ascii=False, indent=2), "format": "json"}
        return {"formatted": yaml.safe_dump(data, allow_unicode=True, sort_keys=False), "format": "yaml"}

    if mode == "extract":
        path = args.get("path")
        if not path:
            raise ToolBusinessError("extract 模式需要 path 参数，例如 path='a.b[0].c'")
        value = _walk(data, path)
        return {"path": path, "value": value, "type": type(value).__name__}

    if mode == "convert":
        to = args.get("to", "yaml")
        if to == "json":
            return {"converted": json.dumps(data, ensure_ascii=False, indent=2), "format": "json"}
        if to == "yaml":
            return {"converted": yaml.safe_dump(data, allow_unicode=True, sort_keys=False), "format": "yaml"}
        raise ToolBusinessError("to 只支持 json / yaml")

    raise ToolBusinessError(f"不支持的 mode：{mode}（validate / format / extract / convert）")


TOOL = ToolDefinition(
    name="json_tool",
    description=(
        "处理 JSON/YAML：validate 校验、format 格式化、extract 按路径取值（如 a.b[0].c）、convert 互转。"
        "确定性实现，校验与取值结果绝对准确，文件太长或嵌套太深时优先用它而不是肉眼检查。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "input": {"type": "string", "description": "JSON 或 YAML 文本"},
            "mode": {"type": "string", "description": "validate | format | extract | convert（默认 validate）"},
            "format": {"type": "string", "description": "输入格式：json | yaml | auto（默认 auto）"},
            "path": {"type": "string", "description": "extract 模式下的取值路径，如 data.items[0].name"},
            "to": {"type": "string", "description": "convert 目标格式：json | yaml"},
        },
        "required": ["input"],
    },
    func=json_tool,
    timeout=15,
)
"""Tool result serialization: valid JSON, head/tail truncation, previews."""
import json

from app.config import settings

_EXEC_TOOLS = {"run_command", "run_code", "local_run_command"}
_MAX_LIST_ITEMS = 50
_TRUNCATION_MARK = "\n… [truncated {n} chars] …\n"


def budget_for(name: str) -> int:
    base = max(int(settings.tool_result_max_chars), 1000)
    if name in _EXEC_TOOLS:
        return min(base + 4000, 20_000)
    return base


def _cap_string(value: str, cap: int, key: str) -> tuple[str, int]:
    if len(value) <= cap:
        return value, 0
    tail_ratio = 0.6 if key in ("stdout", "stderr") else 0.4
    head_len = max(1, int(cap * (1 - tail_ratio)))
    tail_len = max(1, cap - head_len)
    removed = len(value) - head_len - tail_len
    marked = value[:head_len] + _TRUNCATION_MARK.format(n=removed) + value[-tail_len:]
    return marked, removed


def _cap_value(value, cap: int, key: str = "") -> tuple[object, int]:
    if isinstance(value, str):
        return _cap_string(value, cap, key)
    if isinstance(value, list):
        removed = max(0, len(value) - _MAX_LIST_ITEMS)
        capped = []
        for item in value[:_MAX_LIST_ITEMS]:
            shrunk, dropped = _cap_value(item, cap, key)
            capped.append(shrunk)
            removed += dropped
        return capped, removed
    if isinstance(value, dict):
        removed = 0
        out = {}
        for child_key, child in value.items():
            if isinstance(child, list) and len(child) > _MAX_LIST_ITEMS:
                dropped_items = len(child) - _MAX_LIST_ITEMS
                out[f"{child_key}_truncated"] = dropped_items
                removed += dropped_items
                child = child[:_MAX_LIST_ITEMS]
            shrunk, dropped = _cap_value(child, cap, child_key)
            out[child_key] = shrunk
            removed += dropped
        return out, removed
    return value, 0


def _shrink(payload: dict, budget: int) -> tuple[dict, int]:
    cap = max(200, budget // 4)
    shrunk: dict = payload
    removed = 0
    for _ in range(6):
        shrunk, removed = _cap_value(payload, cap)
        text = json.dumps(shrunk, ensure_ascii=False, default=str)
        if len(text) <= budget:
            return shrunk, removed
        cap = max(120, cap // 2)
    return shrunk, max(removed, len(text) - budget)


def serialize_tool_result(name: str, result: dict) -> str:
    payload = {"ok": bool(result.get("ok"))}
    if result.get("ok"):
        payload["output"] = result.get("output")
    else:
        payload["error"] = result.get("error", "unknown error")
    payload["ms"] = int(result.get("ms") or 0)

    shrunk, removed = _shrink(payload, budget_for(name))
    if removed:
        shrunk["_truncated"] = True
        shrunk["_truncated_chars"] = removed
        shrunk["_hint"] = (
            "结果过大，已截断；请缩小查询范围或分页读取，"
            "不要假设已看到全部内容。"
        )
    return json.dumps(shrunk, ensure_ascii=False, default=str)


# Search results are shown as links in the timeline, so their preview keeps
# enough JSON for the client to parse instead of cutting it at 400 chars.
_PREVIEW_LIMITS = {"web_search": 6000}


def build_preview(name: str, result: dict, limit: int | None = None) -> str:
    if limit is None:
        limit = _PREVIEW_LIMITS.get(name, 400)
    if not result.get("ok"):
        return f"错误：{result.get('error', 'unknown error')}"[:limit]

    output = result.get("output")
    if isinstance(output, dict):
        parts: list[str] = []
        command = output.get("command")
        if command:
            parts.append(str(command))
        if "exit_code" in output:
            parts.append(f"exit_code={output['exit_code']}")
        tail = output.get("stderr") or output.get("stdout")
        if isinstance(tail, str) and tail.strip():
            parts.append(tail.strip()[-max(80, limit // 2):])
        if parts:
            return " | ".join(parts)[:limit]

    text = json.dumps(output, ensure_ascii=False, default=str)
    return text[:limit]

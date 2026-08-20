"""Error diagnosis skill: parse a stack trace and cross-search the knowledge base."""
import re

from app.core.tools.base import Tool, ToolError

_ERROR_LINE = re.compile(
    r"\b([A-Za-z_.]*(?:Error|Exception|Warning|Timeout|Failure)[A-Za-z_.]*)\s*[:：]\s*(.+)"
)
_LOCATION = re.compile(r'(?:File\s+")([^"]+)", line (\d+)|at\s+([\w.$/]+)\(([^)]+):(\d+)\)')

_MAX_INPUT_CHARS = 6000
_MAX_HITS = 3
_EXCERPT = 200


async def diagnose_error(error_text: str) -> dict:
    """Tool handler: extract error type/message/locations + KB cross-search."""
    if not error_text or not error_text.strip():
        raise ToolError("empty error text")
    if len(error_text) > _MAX_INPUT_CHARS:
        raise ToolError(f"error text too long (max {_MAX_INPUT_CHARS} chars)")

    lines = [l.strip() for l in error_text.strip().splitlines() if l.strip()]

    # Python: the last matching line is the exception; JVM/others: first match
    error_type, message = None, None
    for l in reversed(lines):
        m = _ERROR_LINE.search(l)
        if m:
            error_type, message = m.group(1), m.group(2).strip()
            break
    if not error_type:
        for l in lines:
            m = _ERROR_LINE.search(l)
            if m:
                error_type, message = m.group(1), m.group(2).strip()
                break

    locations = []
    for m in _LOCATION.finditer(error_text):
        if m.group(1):  # Python style: File "x.py", line N
            locations.append({"file": m.group(1), "line": int(m.group(2))})
        else:  # JVM style: at com.x.Class.method(File.java:120)
            locations.append({"file": m.group(4), "line": int(m.group(5)),
                              "method": m.group(3)})
    locations = locations[:5]

    # Cross-search the knowledge base — best effort, never blocks diagnosis
    knowledge_hits = []
    if error_type:
        try:
            from app.core.rag.retriever import retrieve
            chunks = await retrieve(f"{error_type} {message or ''}".strip(), top_k=_MAX_HITS)
            knowledge_hits = [
                {"source": c.source, "score_type": c.score_type, "excerpt": c.content[:_EXCERPT]}
                for c in chunks
            ]
        except Exception:
            pass

    return {
        "error_type": error_type,
        "message": message,
        "locations": locations,
        "line_count": len(lines),
        "knowledge_hits": knowledge_hits,
        "hint": (
            f"解析到 {error_type or '未知'} 错误"
            + (f"，位置 {locations[0]['file']}:{locations[0]['line']}" if locations else "")
            + (f"；知识库命中 {len(knowledge_hits)} 条相关内容" if knowledge_hits else "")
        ),
    }


error_diagnosis_tool = Tool(
    name="error_diagnosis",
    description=(
        "报错诊断工具。输入一段完整的报错信息或堆栈跟踪（stack trace），"
        "自动解析错误类型、错误消息、出错文件与行号，并到知识库中检索相关"
        "技术资料辅助定位。当用户贴出报错让你帮忙分析原因时调用。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "error_text": {
                "type": "string",
                "description": "完整的报错文本或堆栈跟踪，尽量包含 Traceback 全文",
            },
        },
        "required": ["error_text"],
    },
    handler=diagnose_error,
)

"""diagnose_error tool: parse stack traces / logs (Python, JVM, Node, Go)
and locate the failing code inside the indexed repos."""
import re

from app.core.rag.retriever import retrieve
from app.core.tools.base import ToolBusinessError, ToolContext, ToolDefinition

_PY_FRAME = re.compile(r'File "([^"]+)", line (\d+), in (\S+)')
_PY_ERROR = re.compile(r"^([A-Za-z_][\w.]*(?:Error|Exception|Warning)):?\s*(.*)$")

_JVM_FRAME = re.compile(r"at ([\w$.<>]+)\((\w+\.java):(\d+)\)")
_JVM_ERROR = re.compile(
    r"(?:Exception|Error) in thread \"[^\"]*\"\s+([\w$.]+)(?::\s*(.*))?|Caused by:\s*([\w$.]+)(?::\s*(.*))?"
)

_NODE_FRAME = re.compile(r"at (?:\w+ )?\(?(?:async )?([^\s()]+):(\d+):(\d+)\)?")
_NODE_ERROR = re.compile(r"^([A-Z]\w*Error):\s*(.*)$")

_GO_FRAME = re.compile(r"^\s*([\w./\\\-]+\.go):(\d+)")
_GO_PANIC = re.compile(r"^panic:\s*(.*)$")

MAX_FRAMES = 8


def parse_trace(text: str) -> dict:
    lines = text.splitlines()
    language, error_type, message = "", "", ""
    frames: list[dict] = []

    for line in lines:
        m = _PY_FRAME.search(line)
        if m:
            language = language or "python"
            frames.append({"file": m.group(1), "line": int(m.group(2)), "func": m.group(3)})
        m = _JVM_FRAME.search(line)
        if m:
            language = language or "java"
            frames.append({"file": m.group(2), "line": int(m.group(3)), "func": m.group(1)})
        m = _JVM_ERROR.search(line)
        if m:
            language = language or "java"
            error_type = error_type or (m.group(1) or m.group(3) or "")
            message = message or (m.group(2) or m.group(4) or "")
        m = _NODE_FRAME.search(line)
        if m and not _PY_FRAME.search(line):
            language = language or "javascript"
            frames.append({"file": m.group(1), "line": int(m.group(2)), "func": ""})
        m = _NODE_ERROR.search(line)
        if m:
            language = language or "javascript"
            error_type = error_type or m.group(1)
            message = message or m.group(2)
        m = _GO_FRAME.search(line)
        if m:
            language = language or "go"
            frames.append({"file": m.group(1), "line": int(m.group(2)), "func": ""})
        m = _GO_PANIC.search(line)
        if m:
            language = language or "go"
            message = message or m.group(1)

    if language == "python":
        for line in reversed(lines):
            m = _PY_ERROR.match(line.strip())
            if m:
                error_type, message = m.group(1), m.group(2)
                break

    return {
        "language": language or "unknown",
        "error_type": error_type,
        "message": message[:500],
        "frames": frames[:MAX_FRAMES],
    }


async def _locate_frames(frames: list[dict], repo_ids: list[str] | None) -> list[dict]:
    if not repo_ids:
        return []
    from app.db import query as db_query

    located: list[dict] = []
    for frame in frames:
        basename = frame["file"].replace("\\", "/").split("/")[-1]
        if not basename:
            continue
        sql = """
            SELECT f.path FROM repo_files f
            WHERE f.path ILIKE %s
        """
        params: list = [f"%{basename}"]
        if repo_ids:
            sql += " AND f.repo_id = ANY(%s::uuid[])"
            params.append(repo_ids)
        sql += " LIMIT 2"
        try:
            rows = await db_query(sql, tuple(params))
        except Exception:  # noqa: BLE001
            rows = []
        for row in rows:
            located.append({
                "trace_file": frame["file"],
                "trace_line": frame["line"],
                "func": frame["func"],
                "repo_path": row[0],
            })
    return located


async def diagnose_error(args: dict, ctx: ToolContext) -> dict:
    stack = args.get("stack") or ""
    if not stack.strip():
        raise ToolBusinessError("stack 不能为空：请粘贴完整报错堆栈或日志")

    parsed = parse_trace(stack)
    repo_ids = list(ctx.repo_ids or [])
    located = await _locate_frames(parsed["frames"], repo_ids)

    query = " ".join(x for x in (parsed["error_type"], parsed["message"]) if x) or stack[:200]
    snippets = []
    try:
        hits = await retrieve(query, top_k=5, repo_ids=repo_ids, user_id=ctx.user["id"])
        snippets = [
            {
                "path": h.path,
                "line_start": h.line_start,
                "line_end": h.line_end,
                "source": h.score_type,
                "content": h.content[:300],
            }
            for h in hits
        ]
    except Exception:  # noqa: BLE001
        pass

    return {
        "parsed": parsed,
        "repo_locations": located,
        "related_code": snippets,
        "note": "以上为确定性解析与仓库定位结果；请结合这些证据分析根因并给出修复建议。",
    }


TOOL = ToolDefinition(
    name="diagnose_error",
    description=(
        "解析报错堆栈/日志（支持 Python / Java(JVM) / Node(JS) / Go），提取错误类型、消息与调用帧，"
        "并在已索引的仓库中定位对应文件与相关代码片段。分析报错前应先调用本工具拿到证据。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "stack": {"type": "string", "description": "完整的报错堆栈或日志文本"},
            "context": {"type": "string", "description": "补充上下文：触发操作、环境等（可选）"},
        },
        "required": ["stack"],
    },
    func=diagnose_error,
    timeout=30,
)
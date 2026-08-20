"""Read-only database query skill: SQL allowlist + table allowlist + forced LIMIT."""
import re

from app.core.tools.base import Tool, ToolError
from app.db.postgres import query_with_columns

ALLOWED_TABLES = {
    "documents",
    "agent_facts",
    "eval_queries",
    "eval_results",
    "eval_corpora",
    "audit_log",
    "chat_sessions",
    "chat_messages",
    "task_states",
}

_FORBIDDEN_KEYWORDS = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|copy|vacuum|call|do|merge)\b",
    re.IGNORECASE,
)

_MAX_ROWS = 50
_CELL_TRUNCATE = 200


def _validate_sql(sql: str) -> str:
    stripped = sql.strip().rstrip(";").strip()
    if not stripped:
        raise ToolError("empty SQL statement")
    if ";" in stripped:
        raise ToolError("multiple statements are not allowed")
    if not stripped.lower().startswith(("select", "with")):
        raise ToolError("only SELECT / WITH read-only queries are allowed")
    if _FORBIDDEN_KEYWORDS.search(stripped):
        raise ToolError("write or DDL keywords are not allowed")
    if not any(re.search(rf"\b{t}\b", stripped.lower()) for t in ALLOWED_TABLES):
        raise ToolError(
            "query must reference one of the allowed tables: "
            + ", ".join(sorted(ALLOWED_TABLES))
        )
    return stripped


def _force_limit(sql: str) -> str:
    """Ensure the query is capped at _MAX_ROWS (append or clamp LIMIT)."""
    match = re.search(r"limit\s+(\d+)\s*$", sql, re.IGNORECASE)
    if match:
        if int(match.group(1)) <= _MAX_ROWS:
            return sql
        return sql[: match.start()] + f"LIMIT {_MAX_ROWS}"
    return f"{sql} LIMIT {_MAX_ROWS}"


def _cell(value) -> str | None:
    if value is None:
        return None
    text = str(value)
    if len(text) > _CELL_TRUNCATE:
        return text[:_CELL_TRUNCATE] + "..."
    return text


async def db_query(sql: str) -> dict:
    """Tool handler: run a validated read-only SQL and return columns + rows."""
    safe_sql = _force_limit(_validate_sql(sql))
    columns, rows = await query_with_columns(safe_sql)
    return {
        "sql": safe_sql,
        "columns": columns,
        "row_count": len(rows),
        "rows": [[_cell(v) for v in row] for row in rows],
    }


db_query_tool = Tool(
    name="db_query",
    description=(
        "只读数据库查询工具。可查询知识库文档(documents)、记忆事实(agent_facts)、"
        "评测数据(eval_queries/eval_results)、审计日志(audit_log)、会话与消息"
        "(chat_sessions/chat_messages)、任务状态(task_states)。仅允许 SELECT 语句，"
        "结果最多返回 50 行。当用户想统计数据、查看记录或核对系统状态时调用。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "sql": {
                "type": "string",
                "description": "只读 SELECT 查询，例如 SELECT source, count(*) FROM documents GROUP BY source",
            },
        },
        "required": ["sql"],
    },
    handler=db_query,
)

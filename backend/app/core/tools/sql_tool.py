"""sql_tool: format SQL and run deterministic static review rules."""
import re

from app.core.tools.base import ToolBusinessError, ToolContext, ToolDefinition

_QUOTED = re.compile(r"('[^']*'|\"[^\"]*\"|`[^`]*`)")

_KEYWORDS = [
    "left outer join", "right outer join", "full outer join", "cross join",
    "inner join", "left join", "right join", "group by", "order by",
    "union all", "insert into", "delete from", "create table", "create index",
    "alter table", "drop table", "partition by", "is not null", "is null",
    "not exists", "not in", "select", "from", "where", "having", "limit",
    "offset", "union", "join", "values", "update", "delete", "insert", "set",
    "and", "or", "on", "as", "distinct", "case", "when", "then", "else", "end",
    "between", "like", "in", "exists", "desc", "asc", "with", "null",
]

_NEWLINE_BEFORE = [
    "SELECT", "FROM", "WHERE", "GROUP BY", "ORDER BY", "HAVING", "LIMIT",
    "OFFSET", "UNION ALL", "UNION", "INNER JOIN", "LEFT JOIN", "RIGHT JOIN",
    "CROSS JOIN", "JOIN", "VALUES", "SET", "WITH",
]


def _transform_unquoted(sql: str, fn) -> str:
    parts = _QUOTED.split(sql)
    return "".join(p if i % 2 else fn(p) for i, p in enumerate(parts))


def _uppercase_keywords(sql: str) -> str:
    def up(text: str) -> str:
        for kw in sorted(_KEYWORDS, key=len, reverse=True):
            text = re.sub(rf"(?i)\b{re.escape(kw)}\b", kw.upper(), text)
        return text
    return _transform_unquoted(sql, up)


def format_sql(sql: str) -> str:
    formatted = _uppercase_keywords(sql)
    for clause in _NEWLINE_BEFORE:
        formatted = re.sub(rf"[ \t]+{re.escape(clause)}\b", f"\n{clause}", formatted)
    formatted = re.sub(r"\n(AND|OR)\b", r"\n  \1", formatted)
    formatted = re.sub(r"[ \t]+", " ", formatted)
    formatted = re.sub(r"\n{2,}", "\n", formatted)
    return formatted.strip()


def review_sql(sql: str) -> list[dict]:
    findings: list[dict] = []
    lower = _transform_unquoted(sql, str.lower)
    stripped = lower.strip()

    def add(severity: str, rule: str, message: str, hint: str) -> None:
        findings.append({"severity": severity, "rule": rule, "message": message, "hint": hint})

    if re.search(r"\bselect\s+\*", stripped):
        add("warn", "select_star", "使用了 SELECT *", "显式列出字段，避免依赖列顺序、减少传输与索引覆盖失败")

    if re.match(r"^(update|delete)\b", stripped) and "where" not in stripped:
        add("critical", "no_where", "UPDATE/DELETE 没有 WHERE 子句", "确认是否要全表修改/删除；补充 WHERE 条件")

    if re.search(r"\blike\s+'%", lower):
        add("warn", "leading_wildcard", "LIKE 以 % 开头", "前缀通配无法走索引，考虑全文检索或调整匹配方式")

    if re.search(r"(=|!=|<>)\s*null\b", lower):
        add("warn", "eq_null", "用 = / != 与 NULL 比较", "NULL 比较应使用 IS NULL / IS NOT NULL")

    if re.search(r"\bor\s+1\s*=\s*1\b", lower):
        add("critical", "always_true", "出现 OR 1=1 条件", "恒真条件常见于注入攻击或误写，请核实")

    if re.search(r"\bnot\s+in\s*\(\s*select", lower):
        add("info", "not_in_subquery", "NOT IN (子查询)", "NOT IN 遇 NULL 结果反常且效率低，建议改用 LEFT JOIN ... IS NULL")

    if re.search(r"\bin\s*\(\s*select", lower):
        add("info", "in_subquery", "IN (子查询)", "多数场景 JOIN 改写更利于优化器")

    if re.search(r"\bselect\b", stripped) and "limit" not in stripped and "count(" not in stripped:
        add("info", "no_limit", "查询没有 LIMIT", "面向接口的查询建议加 LIMIT 或分页，避免大结果集")

    return findings


async def sql_tool(args: dict, ctx: ToolContext) -> dict:
    sql = (args.get("sql") or "").strip()
    if not sql:
        raise ToolBusinessError("sql 不能为空")
    mode = args.get("mode", "review")

    if mode == "format":
        return {"formatted": format_sql(sql)}
    if mode == "review":
        findings = review_sql(sql)
        return {
            "findings": findings,
            "formatted": format_sql(sql),
            "note": "静态规则检查，非数据库实测；结论请结合表结构与执行计划判断。",
        }
    if mode == "both":
        return {"formatted": format_sql(sql), "findings": review_sql(sql)}
    raise ToolBusinessError(f"不支持的 mode：{mode}（format / review / both）")


TOOL = ToolDefinition(
    name="sql_tool",
    description=(
        "SQL 处理：format 格式化、review 静态审阅（SELECT *、无 WHERE 的 UPDATE/DELETE、"
        "前导通配 LIKE、NULL 比较、恒真条件、子查询改写建议、缺少 LIMIT）。确定性规则，适合快速过一遍 SQL。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "sql": {"type": "string", "description": "SQL 语句"},
            "mode": {"type": "string", "description": "format | review | both（默认 review）"},
        },
        "required": ["sql"],
    },
    func=sql_tool,
    timeout=15,
)
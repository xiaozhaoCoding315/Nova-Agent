"""Document parser skill: locate a knowledge-base document by name/keyword and return its structure."""
from app.core.tools.base import Tool
from app.db.postgres import query_with_columns

_MAX_SOURCES = 5
_PREVIEW_CHUNKS = 3
_PREVIEW_CHARS = 500


async def parse_document(query: str) -> dict:
    """Tool handler: find matching documents and preview the best match.

    Matching strategy: split the query into keywords and require ALL of them
    (AND) — first against the source filename, then against chunk content.
    This tolerates separator/wording gaps, e.g. "NovaTech 面试题" still hits
    "NovaTech_Agent_面试题.md".
    """
    import re as _re
    words = [w for w in _re.split(r"\s+", query.strip()) if w] or [query.strip()]

    def _all_like(column: str) -> str:
        return " AND ".join([f"{column} ILIKE %s"] * len(words))

    _cols, sources = await query_with_columns(
        "SELECT source, count(*) AS chunks, sum(length(content)) AS total_chars "
        "FROM documents "
        f"WHERE {_all_like('source')} OR {_all_like('content')} "
        "GROUP BY source ORDER BY count(*) DESC LIMIT %s",
        tuple(f"%{w}%" for w in words) * 2 + (_MAX_SOURCES,),
    )
    if not sources:
        return {"found": False, "query": query, "sources": []}

    top_source = sources[0][0]
    _cols2, chunks = await query_with_columns(
        "SELECT (metadata->>'chunk_index'), content FROM documents "
        "WHERE source = %s "
        "ORDER BY (metadata->>'chunk_index')::int NULLS LAST LIMIT %s",
        (top_source, _PREVIEW_CHUNKS),
    )

    previews = []
    for chunk_index, content in chunks:
        text = content or ""
        if len(text) > _PREVIEW_CHARS:
            text = text[:_PREVIEW_CHARS] + "..."
        previews.append({"chunk_index": chunk_index, "preview": text})

    return {
        "found": True,
        "query": query,
        "matched_sources": [
            {"source": s, "chunks": int(c), "total_chars": int(t or 0)}
            for s, c, t in sources
        ],
        "top_source": top_source,
        "previews": previews,
        "hint": f"文档 {top_source} 共 {sources[0][1]} 个分块，以上为前 {len(previews)} 块预览",
    }


doc_parser_tool = Tool(
    name="doc_parser",
    description=(
        "知识库文档解析工具。按文档名称或内容关键词定位已上传的知识库文档，"
        "返回匹配文档列表（分块数、总字数）与最匹配文档的前几个分块预览。"
        "当用户想了解某篇文档的结构、开头内容，或按名字查找文档时调用。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "文档名称或内容关键词，例如 'FastAPI' 或 '部署文档'",
            },
        },
        "required": ["query"],
    },
    handler=parse_document,
)

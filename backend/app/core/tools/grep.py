"""grep tool: exact regex search over the repository filesystem."""
import asyncio
import re
from pathlib import Path

from app.core.indexing.languages import looks_binary
from app.core.security.paths import is_secret_path
from app.core.tools._search import (
    MAX_FILE_BYTES, MAX_SCANNED_FILES, glob_to_regex, is_inside, iter_files,
    matches_patterns, resolve_scope,
)
from app.core.tools.base import ToolBusinessError, ToolContext, ToolDefinition

MAX_PATTERN_CHARS = 500
MAX_RESULTS = 200
DEFAULT_RESULTS = 100
MAX_CONTEXT_LINES = 5


def _scan(
    root: Path,
    start: Path,
    regex: re.Pattern,
    patterns: list[re.Pattern],
    output_mode: str,
    context_lines: int,
    max_results: int,
) -> dict:
    matches: list[dict] = []
    files: list[dict] = []
    counts: list[dict] = []
    scanned = 0
    truncated = False

    for path in iter_files(root, start):
        if scanned >= MAX_SCANNED_FILES:
            truncated = True
            break
        if not is_inside(root, path):
            continue
        try:
            rel = path.relative_to(root).as_posix()
        except ValueError:
            continue
        try:
            resolved_rel = path.resolve().relative_to(root).as_posix()
        except (OSError, ValueError):
            continue
        if (
            is_secret_path(rel)
            or is_secret_path(resolved_rel)
            or not matches_patterns(rel, patterns)
        ):
            continue
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
            data = path.read_bytes()
        except OSError:
            continue
        if looks_binary(data):
            continue
        scanned += 1
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("utf-8", errors="replace")

        lines = text.splitlines()
        file_matches = 0
        for index, line in enumerate(lines):
            if not regex.search(line):
                continue
            file_matches += 1
            if output_mode == "content":
                if len(matches) >= max_results:
                    truncated = True
                    break
                entry = {"path": rel, "line": index + 1, "text": line[:500]}
                if context_lines:
                    entry["before"] = [
                        item[:500] for item in lines[max(0, index - context_lines):index]
                    ]
                    entry["after"] = [
                        item[:500] for item in lines[index + 1:index + 1 + context_lines]
                    ]
                matches.append(entry)

        if output_mode == "content" and len(matches) >= max_results:
            truncated = True
            break
        if output_mode == "files_with_matches" and file_matches:
            if len(files) >= max_results:
                truncated = True
                break
            files.append({"path": rel, "count": file_matches})
        if output_mode == "count" and file_matches:
            if len(counts) >= max_results:
                truncated = True
                break
            counts.append({"path": rel, "count": file_matches})

    payload = {"scanned_files": scanned, "truncated": truncated}
    if output_mode == "content":
        payload.update({"matches": matches, "match_count": len(matches)})
    elif output_mode == "files_with_matches":
        payload.update({"matches": [], "files": files, "file_count": len(files)})
    else:
        payload.update({
            "matches": [],
            "counts": counts,
            "total": sum(item["count"] for item in counts),
        })
    return payload


async def grep(args: dict, ctx: ToolContext) -> dict:
    pattern = str(args.get("pattern") or "")
    if not pattern:
        raise ToolBusinessError("pattern 不能为空")
    if len(pattern) > MAX_PATTERN_CHARS:
        raise ToolBusinessError(f"pattern 过长（上限 {MAX_PATTERN_CHARS} 字符）")

    flags = 0 if args.get("case_sensitive") else re.IGNORECASE
    try:
        regex = re.compile(pattern, flags)
    except re.error as exc:
        raise ToolBusinessError(f"pattern 不是合法正则：{exc}")

    output_mode = str(args.get("output_mode") or "content")
    if output_mode not in ("content", "files_with_matches", "count"):
        raise ToolBusinessError("output_mode 必须是 content / files_with_matches / count")

    context_lines = min(max(int(args.get("context_lines") or 0), 0), MAX_CONTEXT_LINES)
    max_results = min(max(int(args.get("max_results") or DEFAULT_RESULTS), 1), MAX_RESULTS)

    raw_glob = str(args.get("glob") or "")
    patterns = [
        glob_to_regex(part.strip())
        for part in raw_glob.split(",")
        if part.strip()
    ]

    root, start, repo_name = await resolve_scope(args, ctx)
    result = await asyncio.to_thread(
        _scan, root, start, regex, patterns, output_mode, context_lines, max_results
    )
    return {"repo": repo_name, **result}


TOOL = ToolDefinition(
    name="grep",
    description=(
        "在仓库文件系统中做精确正则搜索（不依赖索引，刚写入的文件也能搜到）。"
        "用于查找具体字符串、函数调用、配置项；按文件名查找用 glob，"
        "语义/符号检索用 search_code。默认返回匹配行；"
        "output_mode 可只返回文件列表或计数。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Python 正则表达式，最长 500 字符"},
            "path": {"type": "string", "description": "限定目录或文件（仓库内相对路径，可选）"},
            "glob": {"type": "string", "description": "文件名过滤，逗号分隔，如 '*.py,*.ts'"},
            "case_sensitive": {"type": "boolean", "description": "是否区分大小写（默认 false）"},
            "output_mode": {
                "type": "string",
                "enum": ["content", "files_with_matches", "count"],
                "description": "content=匹配行；files_with_matches=文件列表；count=计数",
            },
            "context_lines": {"type": "integer", "description": "上下文行数（0-5，默认 0）"},
            "max_results": {"type": "integer", "description": "最多返回条数（默认 100，上限 200）"},
            "repo_id": {"type": "string", "description": "仓库 UUID（可选，默认取会话关联仓库）"},
        },
        "required": ["pattern"],
    },
    func=grep,
    category="read",
    capabilities=["fs.read"],
    parallel_safe=True,
    timeout=20,
)

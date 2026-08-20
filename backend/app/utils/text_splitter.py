import re
import uuid
from dataclasses import dataclass

@dataclass
class Chunk:
    id: str
    content: str
    source: str
    metadata: dict


# ---------------------------------------------------------------------------
# Language-aware chunking for source code files
# ---------------------------------------------------------------------------

_CODE_LANGUAGES = {
    ".py": "python", ".java": "java", ".ts": "typescript", ".tsx": "typescript",
    ".js": "javascript", ".jsx": "javascript", ".go": "go", ".rs": "rust",
    ".cpp": "cpp", ".cc": "cpp", ".c": "c", ".h": "c", ".hpp": "cpp",
    ".cs": "csharp", ".rb": "ruby", ".php": "php", ".kt": "kotlin",
    ".swift": "swift", ".sql": "sql", ".sh": "shell", ".yaml": "yaml",
    ".yml": "yaml", ".json": "json", ".toml": "toml",
}

# Top-level declaration patterns per language family — chunks split at these
# boundaries so a function/class stays in one chunk (检索时上下文完整).
_TOP_LEVEL_DECL = {
    "python": re.compile(r"^(?:async\s+def|def|class)\s", re.MULTILINE),
    "java": re.compile(r"^(?:public|private|protected|class|interface|enum|@)\s", re.MULTILINE),
    "typescript": re.compile(r"^(?:export\s+)?(?:default\s+)?(?:async\s+)?(?:function|class|interface|type|enum|const|export)\s", re.MULTILINE),
    "javascript": re.compile(r"^(?:export\s+)?(?:async\s+)?(?:function|class|const|let|export)\s", re.MULTILINE),
    "go": re.compile(r"^func\s", re.MULTILINE),
}
_TOP_LEVEL_DECL["csharp"] = _TOP_LEVEL_DECL["java"]
_TOP_LEVEL_DECL["kotlin"] = _TOP_LEVEL_DECL["java"]
_TOP_LEVEL_DECL["rust"] = re.compile(r"^(?:pub\s+)?(?:fn|struct|enum|impl|trait|mod)\s", re.MULTILINE)
_TOP_LEVEL_DECL["cpp"] = _TOP_LEVEL_DECL["c"] = re.compile(r"^[A-Za-z_].*[({]\s*$", re.MULTILINE)

_CODE_CHUNK_SIZE = 1200
_CODE_OVERLAP_LINES = 5


def detect_language(filename: str) -> str | None:
    name = (filename or "").lower()
    for ext, lang in _CODE_LANGUAGES.items():
        if name.endswith(ext):
            return lang
    return None


def chunk_code(text: str, source: str, language: str) -> list[Chunk]:
    """Split source code at top-level declaration boundaries.

    Falls back to a line-window splitter for oversized blocks so the
    result is always bounded by _CODE_CHUNK_SIZE.
    """
    pattern = _TOP_LEVEL_DECL.get(language)
    if pattern is None:
        return _chunk_code_by_lines(text, source, language, 0)

    # 找到所有顶层声明位置，声明行之间的文本构成候选块
    starts = [m.start() for m in pattern.finditer(text)]
    if not starts:
        return _chunk_code_by_lines(text, source, language, 0)
    if starts[0] != 0:
        starts.insert(0, 0)

    chunks: list[Chunk] = []
    chunk_idx = 0
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(text)
        block = text[start:end].strip("\n")
        if not block.strip():
            continue
        if len(block) <= _CODE_CHUNK_SIZE:
            chunks.append(Chunk(
                id=str(uuid.uuid4()), content=block, source=source,
                metadata={"chunk_index": chunk_idx, "language": language},
            ))
            chunk_idx += 1
        else:
            parts = _chunk_code_by_lines(block, source, language, chunk_idx)
            chunks.extend(parts)
            chunk_idx += len(parts)
    return chunks


def _chunk_code_by_lines(text: str, source: str, language: str, start_idx: int) -> list[Chunk]:
    """Line-window fallback for files without declaration boundaries."""
    lines = text.split("\n")
    chunks: list[Chunk] = []
    buf: list[str] = []
    buf_len = 0
    idx = start_idx
    for line in lines:
        if buf_len + len(line) > _CODE_CHUNK_SIZE and buf:
            chunks.append(Chunk(
                id=str(uuid.uuid4()), content="\n".join(buf).strip("\n"), source=source,
                metadata={"chunk_index": idx, "language": language},
            ))
            idx += 1
            buf = buf[-_CODE_OVERLAP_LINES:]
            buf_len = sum(len(l) for l in buf) + len(buf)
        buf.append(line)
        buf_len += len(line) + 1
    if buf and "\n".join(buf).strip():
        chunks.append(Chunk(
            id=str(uuid.uuid4()), content="\n".join(buf).strip("\n"), source=source,
            metadata={"chunk_index": idx, "language": language},
        ))
        idx += 1
    return chunks


def chunk_document(text: str, source: str) -> list[Chunk]:
    """Entry point: markdown/plain text → prose chunker, code → code chunker."""
    language = detect_language(source)
    if language and language not in ("yaml", "json", "toml", "sql", "shell"):
        return chunk_code(text, source, language)
    if language:  # config/data files: prose chunker works fine
        chunks = chunk_text(text, source)
        for c in chunks:
            c.metadata["language"] = language
        return chunks
    return chunk_text(text, source)

def clean_markdown(text: str) -> str:
    text = re.sub(r'!\[.*?\]\(.*?\)', '', text)
    text = re.sub(r'<!--.*?-->', '', text, flags=re.DOTALL)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'^\s+', '', text, flags=re.MULTILINE)
    return text.strip()

def chunk_text(text: str, source: str, max_chunk_size: int = 800, overlap: int = 100) -> list:
    chunks = []
    sections = re.split(r'(?=#{1,3}\s)', text)
    chunk_idx = 0
    for section in sections:
        section = section.strip()
        if not section:
            continue
        if len(section) <= max_chunk_size:
            uid = str(uuid.uuid4())
            chunks.append(Chunk(id=uid, content=section, source=source, metadata={"chunk_index": chunk_idx}))
            chunk_idx += 1
            continue
        parts = section.split('\n\n')
        buffer = ""
        for part in parts:
            if len(buffer) + len(part) > max_chunk_size and buffer:
                uid = str(uuid.uuid4())
                chunks.append(Chunk(id=uid, content=buffer.strip(), source=source, metadata={"chunk_index": chunk_idx}))
                buffer = buffer[-overlap:] + '\n\n' + part
                chunk_idx += 1
            else:
                buffer = buffer + '\n\n' + part if buffer else part
        if buffer.strip():
            uid = str(uuid.uuid4())
            chunks.append(Chunk(id=uid, content=buffer.strip(), source=source, metadata={"chunk_index": chunk_idx}))
            chunk_idx += 1
    return chunks

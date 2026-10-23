"""Chunking with line numbers — every chunk knows where it came from so
answers can cite real ``path:line`` locations.

Code: blocks are derived from symbol boundaries (falling back to line
windows), docs: markdown sections / paragraphs.
"""
from app.core.indexing.symbols import extract_symbols

CODE_CHUNK_CHARS = 1200
DOC_CHUNK_CHARS = 800
MIN_BLOCK_CHARS = 80
LINE_OVERLAP = 5


def _line_windows(lines: list[str], start: int, end: int) -> list[tuple[int, int]]:
    """Split [start, end] (1-based inclusive) into windows under the size cap."""
    windows: list[tuple[int, int]] = []
    buf_start = start
    size = 0
    for i in range(start, end + 1):
        line_len = len(lines[i - 1]) + 1
        if size + line_len > CODE_CHUNK_CHARS and i > buf_start:
            windows.append((buf_start, i - 1))
            buf_start = max(buf_start, i - LINE_OVERLAP)
            size = sum(len(lines[j - 1]) + 1 for j in range(buf_start, i))
        size += line_len
    if buf_start <= end:
        windows.append((buf_start, end))
    return windows


def chunk_code(content: str, lang: str) -> list[dict]:
    lines = content.splitlines()
    if not lines:
        return []

    symbols = sorted(extract_symbols(content, lang), key=lambda s: s["line_start"])
    blocks: list[tuple[int, int]] = []
    cursor = 1
    for sym in symbols:
        start = max(1, min(sym["line_start"], len(lines)))
        end = max(start, min(sym["line_end"], len(lines)))
        if start > cursor:
            blocks.append((cursor, start - 1))
        if blocks and blocks[-1][1] >= start:
            blocks[-1] = (blocks[-1][0], max(blocks[-1][1], end))
        else:
            blocks.append((start, end))
        cursor = max(cursor, end + 1)
    if cursor <= len(lines):
        blocks.append((cursor, len(lines)))

    if not blocks:
        blocks = [(1, len(lines))]

    # Merge tiny adjacent blocks so we don't emit one-line fragments.
    merged: list[tuple[int, int]] = []
    for start, end in blocks:
        text_len = sum(len(lines[j - 1]) + 1 for j in range(start, end + 1))
        if merged:
            prev_start, prev_end = merged[-1]
            prev_len = sum(len(lines[j - 1]) + 1 for j in range(prev_start, prev_end + 1))
            if text_len < MIN_BLOCK_CHARS or prev_len < MIN_BLOCK_CHARS:
                merged[-1] = (prev_start, end)
                continue
        if text_len < MIN_BLOCK_CHARS and merged:
            merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))

    chunks: list[dict] = []
    for start, end in merged:
        for win_start, win_end in _line_windows(lines, start, end):
            text = "\n".join(lines[win_start - 1:win_end]).strip("\n")
            if not text.strip():
                continue
            chunks.append({
                "content": text,
                "line_start": win_start,
                "line_end": win_end,
                "kind": "code",
                "lang": lang,
            })
    return chunks


def chunk_doc(content: str, lang: str) -> list[dict]:
    lines = content.splitlines()
    chunks: list[dict] = []
    buf_start = 1
    buf: list[str] = []
    buf_len = 0

    def flush(end_line: int) -> None:
        nonlocal buf, buf_len, buf_start
        text = "\n".join(buf).strip("\n")
        if text.strip():
            chunks.append({
                "content": text,
                "line_start": buf_start,
                "line_end": end_line,
                "kind": "doc",
                "lang": lang,
            })
        buf = []
        buf_len = 0

    for i, line in enumerate(lines, start=1):
        is_heading = line.startswith("#") and len(line.lstrip("#")) < len(line)
        if is_heading and buf:
            flush(i - 1)
            buf_start = i
        buf.append(line)
        buf_len += len(line) + 1
        if buf_len > DOC_CHUNK_CHARS:
            flush(i)
            buf_start = i + 1
    if buf:
        flush(len(lines))
    return chunks


def chunk_file(content: str, lang: str, is_doc: bool) -> list[dict]:
    if is_doc:
        return chunk_doc(content, lang)
    return chunk_code(content, lang)
import re

_jieba = None

def _get_jieba():
    global _jieba
    if _jieba is None:
        import jieba
        _jieba = jieba
    return _jieba

def segment(text: str) -> list[str]:
    try:
        jieba = _get_jieba()
        return [w for w in jieba.cut(text) if w.strip()]
    except ImportError:
        return list(text)

def extract_keywords(text: str, top_k: int = 10) -> list[str]:
    try:
        import jieba.analyse
        return jieba.analyse.extract_tags(text, topK=top_k)
    except Exception:
        return segment(text)[:top_k]

def make_tsquery(text: str) -> str:
    """Space-joined jieba tokens for plainto_tsquery (punctuation stripped).

    plainto_tsquery escapes metacharacters for us, so tokens containing e.g.
    ``c++`` or ``foo()`` cannot break the query syntax.
    """
    words = segment(text)
    cleaned = []
    for w in words:
        w = w.strip()
        if not w or not re.search(r"[A-Za-z0-9\u4e00-\u9fff]", w):
            continue
        if re.match(r'^[^\w\u4e00-\u9fff+#]+$', w):
            continue
        cleaned.append(w)
    return " ".join(cleaned[:30])


def tokenized_text(text: str) -> str:
    """jieba-segmented text; feed this to to_tsvector('simple', ...) so that
    Chinese documents and queries are segmented with the same tokenizer."""
    return " ".join(w.strip() for w in segment(text) if w.strip())

def highlight_match(content: str, query: str, max_len: int = 200) -> str:
    keywords = extract_keywords(query, top_k=5)
    lower = content.lower()
    best_pos = -1
    for kw in keywords:
        pos = lower.find(kw.lower())
        if pos >= 0:
            best_pos = pos
            break
    if best_pos < 0:
        return content[:max_len].strip()
    start = max(0, best_pos - 60)
    end = min(len(content), best_pos + max_len - 60)
    snippet = content[start:end].strip()
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(content) else ""
    return f"{prefix}{snippet}{suffix}"

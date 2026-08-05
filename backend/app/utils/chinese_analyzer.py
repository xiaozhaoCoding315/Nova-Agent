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
    words = segment(text)
    words = [w for w in words if len(w.strip()) > 0 and not re.match(r'^[^\w一-鿿]+$', w)]
    if not words:
        return ""
    return " & ".join(words)

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

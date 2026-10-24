"""Context window metering.

给出每次对话上下文构成的估算（不依赖具体 tokenizer，CJK 与拉丁字符分别
按经验比例折算），配合模型上下文窗口配置，前端可以展示「用了多少、用在
哪里」。估算用于可视化；真实总耗点仍以 API 返回的 usage 为准。
"""

# 现代分词器经验值：中文约 0.6~0.8 token/字，拉丁文本约 4 字符/token。
_CJK_RATIO = 0.75
_OTHER_CHARS_PER_TOKEN = 3.8


def estimate_tokens(text: str) -> int:
    """Estimate the token count of a mixed CJK/Latin string."""
    if not text:
        return 0
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff" or "\u3000" <= ch <= "\u303f")
    other = len(text) - cjk
    return max(1, round(cjk * _CJK_RATIO + other / _OTHER_CHARS_PER_TOKEN))


def estimate_messages(messages: list[dict]) -> int:
    """Estimate tokens for a chat message list (content only, plus small overhead)."""
    total = 0
    for message in messages:
        content = message.get("content") if isinstance(message, dict) else None
        total += estimate_tokens(content or "") + 8
    return total

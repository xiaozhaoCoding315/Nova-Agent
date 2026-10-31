"""In-turn context compression.

Tool results are appended verbatim during a turn; long tasks can exceed the
model window.  Before each LLM call we estimate the prompt and, above the
budget, shrink **old** tool results (keep head + tail, drop the middle) while
protecting the system prompt, the most recent messages and the latest test
output tail.  Message order and roles are preserved so tool-call pairing stays
valid.
"""
from dataclasses import dataclass

from app.core.agent.context_meter import estimate_messages

BUDGET_RATIO = 0.8
KEEP_RECENT_MESSAGES = 8
TOOL_HEAD = 800
TOOL_TAIL = 1600
OLD_TEXT_HEAD = 500
OLD_TEXT_TAIL = 500


@dataclass(frozen=True)
class CompactionResult:
    applied: bool
    before: int
    after: int
    compacted: int
    limit: int

    @property
    def saved(self) -> int:
        return max(0, self.before - self.after)


def compact_messages(
    messages: list[dict],
    window: int,
    budget_ratio: float = BUDGET_RATIO,
    keep_recent: int = KEEP_RECENT_MESSAGES,
) -> CompactionResult:
    """Shrink old tool results in place when the prompt exceeds the budget."""
    limit = max(int(window * budget_ratio), 4_000)
    before = estimate_messages(messages)
    if before <= limit or len(messages) <= 2:
        return CompactionResult(False, before, before, 0, limit)

    protected_from = max(1, len(messages) - keep_recent)
    compacted = 0

    def _shrink(index: int, head: int, tail: int) -> bool:
        nonlocal compacted
        message = messages[index]
        content = str(message.get("content") or "")
        if len(content) <= head + tail + 80:
            return False
        omitted = len(content) - head - tail
        message["content"] = (
            content[:head]
            + f"\n…[较早内容已压缩，省略 {omitted} 字符]…\n"
            + content[-tail:]
        )
        compacted += 1
        return True

    # Pass 1: old tool results — the bulk of a long turn.
    for index in range(1, protected_from):
        if messages[index].get("role") != "tool":
            continue
        if estimate_messages(messages) <= limit:
            break
        _shrink(index, TOOL_HEAD, TOOL_TAIL)

    # Pass 2: recent tool results except the very latest one.  A handful of
    # huge recent outputs can still exceed the window on its own.
    last = len(messages) - 1
    for index in range(1, last):
        if estimate_messages(messages) <= limit:
            break
        if messages[index].get("role") != "tool":
            continue
        _shrink(index, 400, 800)

    # Pass 3: old assistant/user text if still over budget.
    for index in range(1, last):
        if estimate_messages(messages) <= limit:
            break
        if messages[index].get("role") == "tool":
            continue
        _shrink(index, OLD_TEXT_HEAD, OLD_TEXT_TAIL)

    after = estimate_messages(messages)
    return CompactionResult(
        applied=compacted > 0, before=before, after=after,
        compacted=compacted, limit=limit,
    )

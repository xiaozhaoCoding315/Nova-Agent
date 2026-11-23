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

# The estimator is a character heuristic; base64 blobs, minified JSON and
# dense logs can be off by 2-3x in either direction.  The loop feeds back
# ``actual_prompt_tokens / estimated`` after every round, clamped to this
# range so one weird round cannot collapse or balloon the budget.
MIN_SCALE = 0.35
MAX_SCALE = 3.0


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


def clamp_scale(scale: float) -> float:
    return min(max(float(scale or 1.0), MIN_SCALE), MAX_SCALE)


def calibration_scale(estimated: int, actual: int) -> float:
    """How far the character estimate was off for one real prompt."""
    if estimated <= 0 or actual <= 0:
        return 1.0
    return clamp_scale(actual / estimated)


def blend_scale(current: float, observed: float, alpha: float = 0.5) -> float:
    """Exponential moving average: one odd round must not rewrite the budget."""
    return clamp_scale((1 - alpha) * current + alpha * observed)


def compaction_limit(
    window: int, budget_ratio: float = BUDGET_RATIO, scale: float = 1.0,
) -> int:
    # Scaling the budget is equivalent to scaling every estimate, and keeps the
    # comparison in one place.  A scale > 1 means the estimator undercounts, so
    # the effective budget must shrink.
    return max(int(window * budget_ratio / clamp_scale(scale)), 4_000)


def needs_compaction(
    messages: list[dict],
    window: int,
    budget_ratio: float = BUDGET_RATIO,
    scale: float = 1.0,
) -> bool:
    """Whether the next LLM call would exceed the compaction budget."""
    return (
        len(messages) > 2
        and estimate_messages(messages) > compaction_limit(window, budget_ratio, scale)
    )


def compact_messages(
    messages: list[dict],
    window: int,
    budget_ratio: float = BUDGET_RATIO,
    keep_recent: int = KEEP_RECENT_MESSAGES,
    scale: float = 1.0,
) -> CompactionResult:
    """Shrink old tool results in place when the prompt exceeds the budget."""
    limit = compaction_limit(window, budget_ratio, scale)
    before = estimate_messages(messages)
    if before <= limit or len(messages) <= 2:
        return CompactionResult(False, before, before, 0, limit)

    protected_from = max(1, len(messages) - keep_recent)
    compacted = 0

    def _shrink(index: int, head: int, tail: int) -> bool:
        nonlocal compacted
        message = messages[index]
        content = message.get("content")
        if not isinstance(content, str):
            return False
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

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


# Placeholder token used while the spilled originals have no database id yet.
# The caller persists them and swaps ``⟦ctxblob:N⟧`` for the real id, so the
# model can pull the dropped middle back instead of losing it for good.
BLOB_TOKEN = "⟦ctxblob:{index}⟧"


class SpillCollector:
    """Records what compaction dropped, so it can be persisted and recalled.

    Compaction is synchronous and in-place; persistence is not.  The collector
    is the seam: compaction writes a placeholder token, the caller stores the
    originals in one batch and rewrites the tokens to real ids.
    """

    def __init__(self) -> None:
        self.originals: list[tuple[str, str]] = []

    def __call__(self, tool_name: str, text: str) -> str:
        self.originals.append((tool_name, text))
        return BLOB_TOKEN.format(index=len(self.originals) - 1)

    def __bool__(self) -> bool:
        return bool(self.originals)


def rewrite_blob_tokens(messages: list[dict], blob_ids: list[int]) -> None:
    """Replace ``⟦ctxblob:N⟧`` with the id the row was stored under.

    Compaction runs before the insert, so the placeholder can only carry the
    index within this batch.  Mapping happens once the ids are known; if the
    insert failed the token stays unresolved and ``context_read`` reports it
    as missing rather than inventing content.
    """
    mapping = {index: blob_id for index, blob_id in enumerate(blob_ids)}
    for message in messages:
        content = message.get("content")
        if not isinstance(content, str) or "⟦ctxblob:" not in content:
            continue
        for index, blob_id in mapping.items():
            content = content.replace(
                f"⟦ctxblob:{index}⟧", f"⟦ctxblob:{blob_id}⟧",
            )
        message["content"] = content


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
    spill: SpillCollector | None = None,
) -> CompactionResult:
    """Shrink old tool results in place when the prompt exceeds the budget.

    ``spill`` receives the dropped middle of every shrunk tool result.  The
    placeholder then carries its token, so the model can call ``context_read``
    to get the original back instead of losing it at the moment it is needed
    most.
    """
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
        hint = f"\n…[较早内容已压缩，省略 {omitted} 字符"
        if spill is not None and message.get("role") == "tool":
            token = spill(
                str(message.get("name") or ""), content[head:len(content) - tail],
            )
            hint += f"；原文见 {token}，可用 context_read 取回"
        message["content"] = content[:head] + hint + "]…\n" + content[-tail:]
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

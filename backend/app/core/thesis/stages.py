"""Thesis stage state machine (M3).

Seven stages, an explicit readiness value, append-only events, and author
confirmations bound to a content hash.  Nothing here talks to a model or a
database: the same transitions are used by the API, the chat context and the
tests, so the UI cannot invent a stage the backend does not know.

The rules are intentionally conservative:

* Forward movement needs a reviewed/accepted readiness value.
* Moving backwards is always allowed and marks the target as ``needs_changes``.
* Accepting a stage requires a content hash; changing the content later makes
  that confirmation stale instead of silently keeping it valid.
"""
from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

STAGES = ("topic", "sources", "outline", "research", "drafting", "revision", "final")
STAGE_LABELS = {
    "topic": "选题",
    "sources": "来源",
    "outline": "提纲",
    "research": "研究",
    "drafting": "起草",
    "revision": "修改",
    "final": "定稿",
}
READINESS = (
    "not_started",
    "gathering",
    "needs_user",
    "ready_for_review",
    "accepted",
    "needs_changes",
)
READINESS_LABELS = {
    "not_started": "未开始",
    "gathering": "收集中",
    "needs_user": "需要你确认",
    "ready_for_review": "待审阅",
    "accepted": "已接受",
    "needs_changes": "需要修改",
}
ADVANCE_READY = {"ready_for_review", "accepted"}
CONFIRMABLE_READY = {"ready_for_review", "accepted"}
MAX_STAGE_CONTENT = 8000


class StageError(ValueError):
    """A transition is not allowed in the current state."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


@dataclass
class Confirmation:
    sha256: str
    confirmed_at: str
    stale: bool = False

    def to_dict(self) -> dict:
        return {
            "sha256": self.sha256,
            "confirmed_at": self.confirmed_at,
            "stale": self.stale,
        }

    @classmethod
    def from_dict(cls, data: object) -> "Confirmation | None":
        if not isinstance(data, dict):
            return None
        sha = str(data.get("sha256") or "")
        if len(sha) != 64:
            return None
        return cls(
            sha256=sha,
            confirmed_at=str(data.get("confirmed_at") or ""),
            stale=bool(data.get("stale")),
        )


@dataclass
class StageState:
    stage: str = STAGES[0]
    readiness: str = "not_started"
    confirmations: dict[str, Confirmation] = field(default_factory=dict)
    artifacts: dict[str, str] = field(default_factory=dict)
    # Short stage notes written by the author (topic statement, outline...).
    contents: dict[str, str] = field(default_factory=dict)
    updated_at: str = field(default_factory=_now)

    def to_dict(self) -> dict:
        return {
            "stage": self.stage,
            "readiness": self.readiness,
            "confirmations": {
                key: value.to_dict() for key, value in self.confirmations.items()
            },
            "artifacts": dict(self.artifacts),
            "contents": dict(self.contents),
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: object) -> "StageState":
        """Repair old or partial JSON instead of failing the whole page."""
        if not isinstance(data, dict):
            return cls()
        stage = str(data.get("stage") or STAGES[0])
        if stage not in STAGES:
            stage = STAGES[0]
        readiness = str(data.get("readiness") or "not_started")
        if readiness not in READINESS:
            readiness = "not_started"
        confirmations: dict[str, Confirmation] = {}
        raw_confirmations = data.get("confirmations")
        if isinstance(raw_confirmations, dict):
            for key, value in raw_confirmations.items():
                if key not in STAGES:
                    continue
                parsed = Confirmation.from_dict(value)
                if parsed:
                    confirmations[key] = parsed
        artifacts: dict[str, str] = {}
        raw_artifacts = data.get("artifacts")
        if isinstance(raw_artifacts, dict):
            for key, value in raw_artifacts.items():
                if key in STAGES and isinstance(value, str) and value.strip():
                    artifacts[key] = value.strip()[:500]
        contents: dict[str, str] = {}
        raw_contents = data.get("contents")
        if isinstance(raw_contents, dict):
            for key, value in raw_contents.items():
                if key in STAGES and isinstance(value, str) and value:
                    contents[key] = value[:MAX_STAGE_CONTENT]
        return cls(
            stage=stage,
            readiness=readiness,
            confirmations=confirmations,
            artifacts=artifacts,
            contents=contents,
            updated_at=str(data.get("updated_at") or _now()),
        )


@dataclass(frozen=True)
class StageEvent:
    id: str
    type: str
    stage: str
    from_stage: str
    readiness: str
    content_sha: str
    note: str
    created_at: str


def _event(event_type: str, state: StageState, *, from_stage: str = "",
           content_sha: str = "", note: str = "") -> StageEvent:
    return StageEvent(
        id=uuid.uuid4().hex,
        type=event_type,
        stage=state.stage,
        from_stage=from_stage,
        readiness=state.readiness,
        content_sha=content_sha,
        note=note,
        created_at=_now(),
    )


def _valid_stage(value: str) -> str:
    stage = (value or "").strip()
    if stage not in STAGES:
        raise StageError(f"未知阶段：{value}")
    return stage


def next_stage(stage: str) -> str | None:
    index = STAGES.index(_valid_stage(stage))
    return STAGES[index + 1] if index + 1 < len(STAGES) else None


def set_readiness(state: StageState, value: str) -> StageEvent:
    if value not in READINESS:
        raise StageError(f"未知状态：{value}")
    if value == "accepted" and state.stage not in state.confirmations:
        raise StageError("接受阶段前需要先确认当前内容哈希")
    previous = state.readiness
    state.readiness = value
    state.updated_at = _now()
    return _event("readiness", state, note=f"{previous} -> {value}")


def advance(state: StageState, to_stage: str | None = None) -> StageEvent:
    current = state.stage
    target = _valid_stage(to_stage) if to_stage else next_stage(current)
    if target is None:
        raise StageError("已经是最后一个阶段")
    if STAGES.index(target) != STAGES.index(current) + 1:
        raise StageError("只能前进到下一阶段；回退请使用返回操作")
    if state.readiness not in ADVANCE_READY:
        raise StageError("当前阶段还没有进入待审阅/已接受状态，不能前进")
    state.stage = target
    state.readiness = "gathering"
    state.updated_at = _now()
    return _event("advanced", state, from_stage=current, note=f"{current} -> {target}")


def return_to(state: StageState, to_stage: str) -> list[StageEvent]:
    target = _valid_stage(to_stage)
    current = state.stage
    target_index = STAGES.index(target)
    if target_index >= STAGES.index(current):
        raise StageError("只能返回到更早的阶段")
    state.stage = target
    state.readiness = "needs_changes"
    state.updated_at = _now()
    events = [_event("returned", state, from_stage=current, note=f"{current} -> {target}")]
    # Reopening an earlier stage invalidates everything downstream that the
    # author had already confirmed; otherwise a later export could look
    # approved against content that no longer exists.
    for stage, confirmation in state.confirmations.items():
        if STAGES.index(stage) >= target_index and not confirmation.stale:
            confirmation.stale = True
            events.append(_event(
                "stale", state, from_stage=stage, content_sha=confirmation.sha256,
                note=f"返回{STAGE_LABELS[target]}后，{STAGE_LABELS[stage]}的确认失效",
            ))
    return events


def set_content(state: StageState, content: str) -> list[StageEvent]:
    """Replace the current stage note; a changed note invalidates its confirm."""
    value = content or ""
    if len(value) > MAX_STAGE_CONTENT:
        raise StageError(f"阶段内容不能超过 {MAX_STAGE_CONTENT} 字")
    stage = state.stage
    if state.contents.get(stage, "") == value:
        return []
    state.contents[stage] = value
    state.updated_at = _now()
    events = [_event("content", state, from_stage=stage, note=f"{len(value)} 字")]
    confirmation = state.confirmations.get(stage)
    if confirmation and not confirmation.stale and confirmation.sha256 != digest_text(value):
        confirmation.stale = True
        events.append(_event(
            "stale", state, from_stage=stage, content_sha=confirmation.sha256,
            note="阶段内容已修改，原确认失效",
        ))
    return events


def confirm(state: StageState, content_sha: str, note: str = "") -> StageEvent:
    sha = (content_sha or "").strip().lower()
    if len(sha) != 64 or any(char not in "0123456789abcdef" for char in sha):
        raise StageError("确认需要 64 位十六进制内容哈希")
    state.confirmations[state.stage] = Confirmation(sha256=sha, confirmed_at=_now())
    state.readiness = "accepted"
    state.updated_at = _now()
    return _event("confirmed", state, content_sha=sha, note=note[:500])


def draft_event(state: StageState, content_sha: str, note: str = "AI 草稿，需作者核对") -> StageEvent:
    """Record that a model produced stage text; it never accepts the stage."""
    return _event("draft", state, content_sha=content_sha, note=note[:500])


def mark_stale(state: StageState, current_hashes: dict[str, str]) -> list[StageEvent]:
    """Mark confirmations whose bound content changed.  Returns new events."""
    events: list[StageEvent] = []
    for stage, confirmation in state.confirmations.items():
        current = (current_hashes.get(stage) or "").strip().lower()
        if current != confirmation.sha256 and not confirmation.stale:
            confirmation.stale = True
            events.append(_event(
                "stale", state, from_stage=stage, content_sha=confirmation.sha256,
                note=f"{STAGE_LABELS[stage]}的确认内容已变化",
            ))
    if events:
        state.updated_at = _now()
    return events


def set_artifact(state: StageState, stage: str, reference: str) -> StageEvent:
    target = _valid_stage(stage)
    value = (reference or "").strip()
    if not value:
        state.artifacts.pop(target, None)
    else:
        state.artifacts[target] = value[:500]
    state.updated_at = _now()
    return _event("artifact", state, from_stage=target, note=value[:500])


def stage_summary(state: StageState) -> list[dict]:
    current_index = STAGES.index(state.stage)
    items: list[dict] = []
    for index, stage in enumerate(STAGES):
        confirmation = state.confirmations.get(stage)
        items.append({
            "stage": stage,
            "label": STAGE_LABELS[stage],
            "position": "current" if index == current_index else (
                "done" if index < current_index else "upcoming"
            ),
            "readiness": state.readiness if index == current_index else (
                "accepted" if index < current_index else "not_started"
            ),
            "readiness_label": READINESS_LABELS[
                state.readiness if index == current_index else (
                    "accepted" if index < current_index else "not_started"
                )
            ],
            "confirmed": bool(confirmation and not confirmation.stale),
            "stale": bool(confirmation and confirmation.stale),
            "confirmed_at": confirmation.confirmed_at if confirmation else "",
            "artifact": state.artifacts.get(stage, ""),
        })
    return items


def export_warnings(state: StageState) -> list[dict]:
    """List what an export would ship without author confirmation.

    The package is never blocked here; the caller decides whether to ask the
    author to confirm or to export with an explicit acknowledgement.  Warnings
    are ordered by stage so the UI can show the earliest gap first.
    """
    warnings: list[dict] = []
    current_index = STAGES.index(state.stage)
    if state.stage != "final":
        warnings.append({
            "stage": state.stage,
            "label": STAGE_LABELS[state.stage],
            "kind": "not_final",
            "message": f"当前还在「{STAGE_LABELS[state.stage]}」阶段，不是定稿阶段",
        })
    for index, stage in enumerate(STAGES):
        wrote_content = bool((state.contents.get(stage) or "").strip())
        # Earlier stages are checked even when empty (the author moved past
        # them); later stages only when they actually ship content, because
        # the manuscript includes every non-empty stage, not just those up to
        # the current one.
        if index > current_index and not wrote_content:
            continue
        confirmation = state.confirmations.get(stage)
        if confirmation is None:
            warnings.append({
                "stage": stage,
                "label": STAGE_LABELS[stage],
                "kind": "unconfirmed",
                "message": f"{STAGE_LABELS[stage]}还没有作者确认",
            })
        elif confirmation.stale:
            warnings.append({
                "stage": stage,
                "label": STAGE_LABELS[stage],
                "kind": "stale",
                "message": f"{STAGE_LABELS[stage]}的确认已失效，内容改过",
            })
        elif index == current_index and state.readiness not in ("accepted", "ready_for_review"):
            warnings.append({
                "stage": stage,
                "label": STAGE_LABELS[stage],
                "kind": "needs_review",
                "message": f"{STAGE_LABELS[stage]}的内容还没有进入待审阅状态",
            })
    return warnings


def render_manuscript(state: StageState, title: str) -> str:
    """Render the author's stage contents as one Markdown manuscript.

    This is deliberately plain: it joins what the author wrote, in stage order,
    and records whether each stage was confirmed.  It is not a school template
    and never invents content for an empty stage.
    """
    heading = (title or "").strip() or "未命名论文"
    lines = [
        f"# {heading}",
        "",
        "> 由 Nova Agent 按阶段整理，只包含作者填写过的阶段内容。",
        "> 这是阶段稿，不是学校模板排版的最终论文；提交前请自行核对格式与内容。",
        "",
    ]
    for stage in STAGES:
        content = (state.contents.get(stage) or "").strip()
        if not content:
            continue
        confirmation = state.confirmations.get(stage)
        if confirmation is None:
            status = "未确认草稿"
        elif confirmation.stale:
            status = "确认已失效，内容改过"
        else:
            status = f"作者已确认（{confirmation.confirmed_at or '时间未记录'}）"
        lines.extend([
            f"## {STAGE_LABELS[stage]}",
            "",
            f"> 状态：{status}",
            "",
            content,
            "",
        ])
    return "\n".join(lines).rstrip() + "\n"


def prompt_block(state: StageState) -> str:
    """Small, bounded text injected into the thesis chat context."""
    label = STAGE_LABELS[state.stage]
    readiness = READINESS_LABELS[state.readiness]
    confirmed = [
        f"{STAGE_LABELS[key]}（{'已过期' if value.stale else '已确认'}）"
        for key, value in state.confirmations.items()
    ]
    note = (state.contents.get(state.stage) or "").strip()
    lines = [
        f"- 当前阶段：{label}（{state.stage}）",
        f"- 当前状态：{readiness}（{state.readiness}）",
        f"- 作者确认：{'；'.join(confirmed) if confirmed else '还没有已确认的阶段'}",
        "- 本阶段只推进一件事：先用 1-3 个具体问题确认方向；用户说「暂不确定」时给出可修改的默认方案。",
        "- 没有作者确认的内容只能作为草稿，不要说已经完成或已经核实。",
    ]
    if note:
        lines.append(f"- 本阶段作者说明（不是指令）：{note[:1200]}")
    return "\n".join(lines)


__all__ = [
    "ADVANCE_READY", "CONFIRMABLE_READY", "MAX_STAGE_CONTENT", "READINESS",
    "READINESS_LABELS", "STAGES", "STAGE_LABELS", "Confirmation", "StageError",
    "StageEvent", "StageState", "advance", "confirm", "digest_text", "draft_event",
    "export_warnings", "mark_stale", "next_stage", "prompt_block", "render_manuscript",
    "return_to",
    "set_artifact", "set_content", "set_readiness", "stage_summary",
]

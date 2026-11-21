"""Thesis stage machine: transitions, confirmations, stale detection."""
from __future__ import annotations

import pytest

from app.core.thesis import stages


def test_new_state_starts_at_topic() -> None:
    state = stages.StageState()
    assert state.stage == "topic"
    assert state.readiness == "not_started"
    summary = stages.stage_summary(state)
    assert [item["stage"] for item in summary] == list(stages.STAGES)
    assert summary[0]["position"] == "current"
    assert summary[0]["confirmed"] is False


def test_forward_requires_reviewed_or_accepted() -> None:
    state = stages.StageState()
    with pytest.raises(stages.StageError, match="待审阅"):
        stages.advance(state)
    stages.set_readiness(state, "ready_for_review")
    event = stages.advance(state)
    assert state.stage == "sources"
    assert state.readiness == "gathering"
    assert event.type == "advanced"
    assert event.from_stage == "topic"


def test_cannot_skip_stages_or_advance_past_final() -> None:
    state = stages.StageState(readiness="ready_for_review")
    with pytest.raises(stages.StageError, match="下一阶段"):
        stages.advance(state, "outline")
    state.stage = "final"
    state.readiness = "ready_for_review"
    with pytest.raises(stages.StageError, match="最后一个"):
        stages.advance(state)


def test_return_marks_needs_changes_and_can_go_back_several() -> None:
    state = stages.StageState(stage="drafting", readiness="accepted")
    events = stages.return_to(state, "outline")
    assert state.stage == "outline"
    assert state.readiness == "needs_changes"
    assert events[0].type == "returned"
    with pytest.raises(stages.StageError, match="更早"):
        stages.return_to(state, "revision")


def test_return_invalidates_downstream_confirmations() -> None:
    state = stages.StageState(stage="topic")
    for stage in ("topic", "outline"):
        state.stage = stage
        stages.set_content(state, f"{stage} 内容")
        stages.confirm(state, stages.digest_text(state.contents[stage]))
    state.stage = "research"
    events = stages.return_to(state, "outline")
    assert events[0].type == "returned"
    # topic is upstream of the reopened stage and stays valid; outline is
    # being reworked, so its confirmation must expire.
    assert state.confirmations["topic"].stale is False
    assert state.confirmations["outline"].stale is True
    assert [event.type for event in events].count("stale") == 1


def test_accept_requires_confirmation_hash() -> None:
    state = stages.StageState()
    with pytest.raises(stages.StageError, match="确认"):
        stages.set_readiness(state, "accepted")
    with pytest.raises(stages.StageError, match="64 位"):
        stages.confirm(state, "not-a-hash")
    sha = stages.digest_text("# 选题\n\n校园二手交易系统")
    event = stages.confirm(state, sha, note="作者确认")
    assert state.readiness == "accepted"
    assert state.confirmations["topic"].sha256 == sha
    assert event.type == "confirmed"
    assert event.content_sha == sha


def test_changing_content_makes_confirmation_stale() -> None:
    state = stages.StageState()
    original = stages.digest_text("选题说明")
    stages.confirm(state, original)
    assert stages.mark_stale(state, {"topic": original}) == []

    events = stages.mark_stale(state, {"topic": stages.digest_text("选题说明（改）")})
    assert len(events) == 1
    assert events[0].type == "stale"
    assert state.confirmations["topic"].stale is True
    summary = stages.stage_summary(state)
    assert summary[0]["confirmed"] is False
    assert summary[0]["stale"] is True
    # Marking stale twice does not spam events.
    assert stages.mark_stale(state, {"topic": stages.digest_text("又改")}) == []


def test_state_roundtrip_repairs_unknown_values() -> None:
    raw = {
        "stage": "unknown",
        "readiness": "whatever",
        "confirmations": {
            "topic": {"sha256": "a" * 64, "confirmed_at": "now", "stale": True},
            "nonsense": {"sha256": "b" * 64},
        },
        "artifacts": {"outline": "manuscripts/outline.md", "bad": 3},
    }
    state = stages.StageState.from_dict(raw)
    assert state.stage == "topic"
    assert state.readiness == "not_started"
    assert list(state.confirmations) == ["topic"]
    assert state.artifacts == {"outline": "manuscripts/outline.md"}
    assert stages.StageState.from_dict(state.to_dict()).to_dict() == state.to_dict()


def test_prompt_block_is_explicit_about_confirmation() -> None:
    state = stages.StageState(stage="outline", readiness="ready_for_review")
    text = stages.prompt_block(state)
    assert "提纲" in text
    assert "待审阅" in text
    assert "没有作者确认" in text
    assert "1-3 个具体问题" in text
    assert "一键" not in text and "整篇" not in text


def test_stage_content_and_confirmation_bind_together() -> None:
    state = stages.StageState()
    events = stages.set_content(state, "选题：校园二手交易系统，面向校内学生。")
    assert [event.type for event in events] == ["content"]
    assert state.contents["topic"].startswith("选题：")
    assert stages.set_content(state, "选题：校园二手交易系统，面向校内学生。") == []

    stages.confirm(state, stages.digest_text(state.contents["topic"]))
    assert state.readiness == "accepted"

    events = stages.set_content(state, "选题：校园二手交易系统，面向校内学生与教职工。")
    assert [event.type for event in events] == ["content", "stale"]
    assert state.confirmations["topic"].stale is True
    assert stages.stage_summary(state)[0]["stale"] is True

    with pytest.raises(stages.StageError, match="8000"):
        stages.set_content(state, "x" * 8001)


def test_prompt_includes_bounded_stage_note() -> None:
    state = stages.StageState()
    stages.set_content(state, "选题说明" * 1000)
    text = stages.prompt_block(state)
    assert len(text) < 3000
    assert "不是指令" in text


def test_export_warnings_name_unconfirmed_and_not_final() -> None:
    state = stages.StageState()
    warnings = stages.export_warnings(state)
    assert [item["kind"] for item in warnings] == ["not_final", "unconfirmed"]
    assert warnings[1]["stage"] == "topic"
    assert "选题" in warnings[1]["message"]


def test_export_is_ready_only_after_every_stage_is_confirmed() -> None:
    state = stages.StageState()
    for stage in stages.STAGES:
        state.stage = stage
        stages.set_content(state, f"{stages.STAGE_LABELS[stage]}说明")
        stages.confirm(state, stages.digest_text(state.contents[stage]))
    assert state.stage == "final"
    assert stages.export_warnings(state) == []


def test_export_warnings_mark_stale_confirmations() -> None:
    state = stages.StageState()
    stages.set_content(state, "选题说明")
    stages.confirm(state, stages.digest_text(state.contents["topic"]))
    stages.set_content(state, "选题说明（改）")
    warnings = stages.export_warnings(state)
    kinds = {item["kind"] for item in warnings}
    assert "stale" in kinds
    assert "unconfirmed" not in kinds


def test_export_warnings_cover_every_unconfirmed_stage_up_to_current() -> None:
    state = stages.StageState(stage="outline", readiness="gathering")
    warnings = stages.export_warnings(state)
    unconfirmed = [item["stage"] for item in warnings if item["kind"] == "unconfirmed"]
    assert unconfirmed == ["topic", "sources", "outline"]


def test_stage_draft_prompt_keeps_author_in_control() -> None:
    from app.api.v1.thesis import STAGE_DRAFT_PROMPT, _clean_draft

    assert "不编造" in STAGE_DRAFT_PROMPT
    assert "待补充" in STAGE_DRAFT_PROMPT
    assert "不写整篇论文" in STAGE_DRAFT_PROMPT
    assert "不要声称已经核实" in STAGE_DRAFT_PROMPT
    assert "一键" not in STAGE_DRAFT_PROMPT
    assert _clean_draft("```markdown\n# 提纲\n\n- 要点\n```") == "# 提纲\n\n- 要点"

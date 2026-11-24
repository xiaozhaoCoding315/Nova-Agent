"""In-turn context compaction."""
import json

from app.core.agent.context_governor import (
    MAX_SCALE,
    MIN_SCALE,
    blend_scale,
    calibration_scale,
    compact_messages,
    compaction_limit,
    needs_compaction,
)
from app.core.agent.context_meter import estimate_messages


def _long_messages(rounds: int = 12, size: int = 20_000):
    messages = [{"role": "system", "content": "system prompt"}]
    for index in range(rounds):
        messages.append({
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": f"t{index}", "type": "function",
                "function": {"name": "run_command",
                             "arguments": json.dumps({"command": "pytest -q"})},
            }],
        })
        messages.append({
            "role": "tool", "tool_call_id": f"t{index}", "name": "run_command",
            "content": f"HEAD-{index} " + "x" * size + f" TAIL-{index}",
        })
    return messages


def test_compacts_old_tool_results_and_keeps_the_latest():
    messages = _long_messages()
    before = estimate_messages(messages)

    result = compact_messages(messages, window=20_000)

    assert result.applied and result.compacted > 0
    assert result.after < before
    assert result.after <= result.limit
    assert messages[0]["content"] == "system prompt"
    assert messages[-1]["content"].startswith("HEAD-11")
    assert messages[-1]["content"].endswith("TAIL-11")
    first_tool = messages[2]["content"]
    assert first_tool.startswith("HEAD-0")
    assert first_tool.endswith("TAIL-0")
    assert "已压缩" in first_tool
    # Protocol shape is untouched.
    assert messages[1]["role"] == "assistant" and messages[1]["tool_calls"]
    assert messages[2]["role"] == "tool" and messages[2]["tool_call_id"] == "t0"


def test_no_compaction_below_budget():
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hi"},
    ]
    result = compact_messages(messages, window=100_000)
    assert not result.applied
    assert result.before == result.after
    assert messages[1]["content"] == "hi"


def test_calibration_scale_tracks_real_usage():
    # Estimator said 1000, the provider billed 2000: prompts are twice as
    # expensive as the character heuristic thinks.
    assert calibration_scale(1000, 2000) == 2.0
    assert calibration_scale(1000, 500) == 0.5
    # Missing or zero data must not move the scale.
    assert calibration_scale(0, 2000) == 1.0
    assert calibration_scale(1000, 0) == 1.0


def test_calibration_scale_is_clamped():
    assert calibration_scale(1000, 100_000) == MAX_SCALE
    assert calibration_scale(1000, 1) == MIN_SCALE


def test_blend_scale_moves_toward_the_observation():
    assert blend_scale(1.0, 3.0) == 2.0
    assert blend_scale(2.0, 1.0) == 1.5
    # A single wild round cannot jump straight to the clamp bound.
    assert blend_scale(1.0, MAX_SCALE) < MAX_SCALE


def test_scale_shrinks_the_effective_budget_when_estimates_undercount():
    window = 100_000
    assert compaction_limit(window, scale=1.0) == 80_000
    # Estimator undercounts 2x → the real prompt is twice the estimate, so the
    # budget expressed in estimated tokens halves.
    assert compaction_limit(window, scale=2.0) == 40_000
    assert compaction_limit(window, scale=0.5) == 160_000


def test_needs_compaction_respects_scale():
    messages = _long_messages(rounds=4, size=4_000)
    estimated = estimate_messages(messages)
    window = max(int(estimated / 0.4), 4_000)  # budget ≈ 0.8 * window > estimated
    assert needs_compaction(messages, window) is False
    # The provider bills 3x what we estimated: the prompt is over budget.
    assert needs_compaction(messages, window, scale=3.0) is True


def test_compact_messages_honours_scale():
    messages = _long_messages(rounds=12, size=6_000)
    # ~19k estimated: under the uncalibrated 32k budget, over the 16k budget
    # that a 2x undercount implies.
    assert not compact_messages(
        _long_messages(rounds=12, size=6_000), window=40_000,
    ).applied
    result = compact_messages(messages, window=40_000, scale=2.0)
    assert result.applied
    assert result.limit == compaction_limit(40_000, scale=2.0)
    assert result.after <= result.limit

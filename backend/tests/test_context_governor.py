"""In-turn context compaction."""
import json

from app.core.agent.context_governor import compact_messages
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

"""Unit tests for eval checks."""
import pytest

from evals.checks import (
    changed_files_exactly,
    file_contains,
    file_exists,
    file_unchanged,
    final_text_contains,
    final_text_matches,
    llm_saw_compaction,
    llm_saw_image,
    no_error_events,
    no_notice,
    notice_seen,
    plan_has_steps,
    pytest_passes,
    tool_failed_with,
    tool_succeeded,
)
from evals.fixtures import create_fixture
from evals.models import CheckFailure, EvalRun, EvalTask, ToolCallRecord

TASK = EvalTask(
    id="check_task",
    mode="scripted",
    category="test",
    description="",
    prompt="",
    fixture="python_small",
    checks=(),
)


@pytest.fixture()
def run():
    repo = create_fixture("python_small")
    yield EvalRun(task=TASK, repo=repo)
    repo.cleanup()


def test_expect_raises_check_failure():
    from evals.checks import expect

    with pytest.raises(CheckFailure, match="boom"):
        expect(False, "boom")


def test_final_text_checks(run):
    run.final_text = "add 返回 a - b，第 1 行"
    final_text_contains("a - b")(run)
    final_text_matches(r"第 \d+ 行")(run)
    with pytest.raises(CheckFailure):
        final_text_contains("a + b")(run)


def test_tool_checks(run):
    run.tool_calls = [
        ToolCallRecord(id="1", name="read_file", args={}, ok=True),
        ToolCallRecord(
            id="2", name="edit_file", args={}, ok=False,
            error="readonly", error_class="policy",
        ),
    ]
    tool_succeeded("read_file")(run)
    tool_failed_with("edit_file", "policy")(run)
    with pytest.raises(CheckFailure):
        tool_succeeded("edit_file")(run)
    with pytest.raises(CheckFailure):
        tool_failed_with("edit_file", "business")(run)


def test_error_and_notice_checks(run):
    no_error_events()(run)
    no_notice("vision_unsupported")(run)
    with pytest.raises(CheckFailure):
        notice_seen("vision_unsupported")(run)
    run.events = [
        {"event": "error", "data": {"message": "x"}},
        {"event": "notice", "data": {"kind": "vision_unsupported"}},
    ]
    with pytest.raises(CheckFailure):
        no_error_events()(run)
    with pytest.raises(CheckFailure):
        no_notice("vision_unsupported")(run)
    notice_seen("vision_unsupported")(run)


def test_file_checks_and_changed_files(run):
    file_exists("calc.py")(run)
    file_contains("calc.py", "return a - b")(run)
    file_unchanged("calc.py")(run)
    changed_files_exactly()(run)

    (run.repo.root / "calc.py").write_text(
        "def add(a, b):\n    return a + b\n", encoding="utf-8"
    )
    changed_files_exactly("calc.py")(run)
    with pytest.raises(CheckFailure):
        file_unchanged("calc.py")(run)

    (run.repo.root / "extra.txt").write_text("x", encoding="utf-8")
    with pytest.raises(CheckFailure):
        changed_files_exactly("calc.py")(run)
    with pytest.raises(CheckFailure):
        changed_files_exactly("calc.py", "extra.txt", "missing.txt")(run)


def test_plan_checks(run):
    run.events = [{
        "event": "plan",
        "data": {
            "steps": [
                {"title": "a", "status": "completed"},
                {"title": "b", "status": "in_progress"},
                {"title": "c", "status": "pending"},
            ]
        },
    }]
    plan_has_steps(3, in_progress=1)(run)
    with pytest.raises(CheckFailure):
        plan_has_steps(4)(run)


def test_llm_message_checks(run):
    run.llm_messages = [[{
        "role": "user",
        "content": [
            {"type": "text", "text": "看图"},
            {
                "type": "image_url",
                "image_url": {"url": "data:image/png;base64,abc"},
            },
        ],
    }]]
    llm_saw_image()(run)
    with pytest.raises(CheckFailure):
        llm_saw_compaction()(run)

    run.llm_messages[0][0]["content"] = "…[较早内容已压缩，省略 100 字符]…"
    llm_saw_compaction()(run)
    with pytest.raises(CheckFailure):
        llm_saw_image()(run)


def test_pytest_passes_checks_current_tree(run):
    with pytest.raises(CheckFailure):
        pytest_passes()(run)

    (run.repo.root / "calc.py").write_text(
        "def add(a, b):\n    return a + b\n\n\n"
        "def multiply(a, b):\n    return a * b\n",
        encoding="utf-8",
    )
    pytest_passes()(run)

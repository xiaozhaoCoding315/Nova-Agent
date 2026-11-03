"""The scripted smoke suite must pass deterministically."""
import pytest

from evals.runner import run_suite, run_task
from evals.tasks import tasks_for_mode
from evals.tasks.smoke import PERMISSION_DENIED, READ_AND_ANSWER

SCRIPTED_IDS = {
    "read_and_answer",
    "edit_file_minimal",
    "write_files_multi",
    "permission_denied",
    "plan_tool",
    "vision_image",
    "context_compaction",
}


@pytest.mark.asyncio
async def test_scripted_smoke_suite_has_expected_tasks():
    tasks = tasks_for_mode("scripted")
    assert {task.id for task in tasks} == SCRIPTED_IDS


@pytest.mark.asyncio
async def test_scripted_smoke_suite_passes():
    report = await run_suite(tasks_for_mode("scripted"), "scripted")
    failures = [task for task in report.tasks if task.status != "passed"]
    assert not failures, [
        (task.task_id, task.status, task.failure, task.error)
        for task in failures
    ]
    assert report.summary["passed"] == 7


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "task", [READ_AND_ANSWER, PERMISSION_DENIED], ids=lambda task: task.id,
)
async def test_scripted_tasks_pass_individually(task):
    result = await run_task(task)
    assert result.status == "passed", (result.failure, result.error)

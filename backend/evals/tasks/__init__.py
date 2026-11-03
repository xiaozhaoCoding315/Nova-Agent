"""Eval task registry."""
from evals.models import EvalMode, EvalTask
from evals.tasks.smoke import ALL_TASKS


def tasks_for_mode(mode: EvalMode) -> list[EvalTask]:
    return [task for task in ALL_TASKS if task.mode == mode]

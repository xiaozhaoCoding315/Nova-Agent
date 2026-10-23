"""Job data structures shared by the runner and its handlers."""
from dataclasses import dataclass
from typing import Any


class JobCanceled(Exception):
    """Raised by a handler when the user canceled the job."""


class JobFailed(Exception):
    """Raised by a handler when the work completed but did not succeed."""


@dataclass
class Job:
    id: str
    user_id: int | None
    kind: str
    payload: dict
    attempts: int = 0
    max_attempts: int = 1


@dataclass
class JobContext:
    """Handler-facing view of one running job."""

    job: Job
    runner: Any

    @property
    def job_id(self) -> str:
        return self.job.id

    @property
    def payload(self) -> dict:
        return self.job.payload

    async def update(self, *, progress: float | None = None, step: str | None = None) -> None:
        await self.runner.update_job(self.job.id, progress=progress, step=step)

    async def check_cancel(self) -> None:
        if await self.runner.is_cancel_requested(self.job.id):
            raise JobCanceled()

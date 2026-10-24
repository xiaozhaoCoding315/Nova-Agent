"""Durable, database-backed background job runner.

Job state lives in PostgreSQL, so a restart does not leave tasks permanently
stuck in ``running``.  Workers claim queued rows with
``FOR UPDATE SKIP LOCKED``, run a registered handler, and update progress and
heartbeats while doing so.

Cancellation is cooperative: handlers call ``ctx.check_cancel()`` at safe
points.  The runner also kills sandbox containers labelled with the job id, so
a long Docker command stops promptly.
"""
import asyncio
import json
import uuid
from dataclasses import dataclass
from typing import Awaitable, Callable

import structlog

from app.config import settings
from app.core.jobs.models import Job, JobCanceled, JobContext
from app.db import execute, query

logger = structlog.get_logger()

Handler = Callable[[JobContext], Awaitable[dict | None]]


@dataclass
class _HandlerSpec:
    fn: Handler
    concurrency: int = 1


class JobRunner:
    def __init__(self) -> None:
        self._handlers: dict[str, _HandlerSpec] = {}
        self._active: dict[str, asyncio.Task] = {}
        self._active_kinds: dict[str, int] = {}
        self._loop_task: asyncio.Task | None = None
        self._heartbeat_task: asyncio.Task | None = None
        self._running = False
        self._wake = asyncio.Event()

    # ------------------------------------------------------------------
    # registration / lifecycle
    # ------------------------------------------------------------------
    def register(self, kind: str, fn: Handler, concurrency: int = 1) -> None:
        if kind in self._handlers:
            raise ValueError(f"job handler already registered: {kind}")
        self._handlers[kind] = _HandlerSpec(fn=fn, concurrency=max(1, concurrency))

    def has(self, kind: str) -> bool:
        return kind in self._handlers

    @property
    def running(self) -> bool:
        return self._running

    async def start(self) -> None:
        if self._running:
            return
        # Import lazily to avoid circular imports at module load time.
        from app.core.jobs import handlers
        handlers.register_all(self)

        self._running = True
        self._wake.clear()
        try:
            await self._recover_stale()
        except Exception as exc:  # noqa: BLE001
            logger.warning("job_recovery_failed", error=str(exc))
        self._loop_task = asyncio.create_task(self._loop(), name="nova-job-runner")
        self._heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(), name="nova-job-heartbeat"
        )
        logger.info("job_runner_started", handlers=sorted(self._handlers))

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        self._wake.set()

        active_ids = list(self._active)
        for task in list(self._active.values()):
            task.cancel()
        if self._active:
            await asyncio.gather(*self._active.values(), return_exceptions=True)

        for task in (self._loop_task, self._heartbeat_task):
            if task:
                task.cancel()
        for task in (self._loop_task, self._heartbeat_task):
            if task:
                try:
                    await task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass

        # A graceful shutdown should not leave jobs running forever.
        if active_ids:
            try:
                await execute(
                    "UPDATE jobs SET status = 'queued', started_at = NULL, "
                    "heartbeat_at = NULL, error = 'server shutdown; job requeued' "
                    "WHERE id = ANY(%s::uuid[]) AND status = 'running'",
                    (active_ids,),
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("job_requeue_on_shutdown_failed", error=str(exc))
        logger.info("job_runner_stopped")

    # ------------------------------------------------------------------
    # public operations
    # ------------------------------------------------------------------
    async def enqueue(
        self,
        kind: str,
        payload: dict,
        *,
        user_id: int | None = None,
        idempotency_key: str | None = None,
        max_attempts: int = 1,
    ) -> str:
        if kind not in self._handlers:
            from app.core.jobs import handlers
            handlers.register_all(self)
        if kind not in self._handlers:
            raise ValueError(f"unknown job kind: {kind}")
        job_id = str(uuid.uuid4())
        payload_json = json.dumps(payload or {}, ensure_ascii=False)
        if idempotency_key:
            rows = await execute(
                """
                INSERT INTO jobs (id, user_id, kind, payload, idempotency_key, max_attempts)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id, idempotency_key) DO NOTHING
                RETURNING id
                """,
                (job_id, user_id, kind, payload_json, idempotency_key, max_attempts),
            )
            if rows:
                job_id = str(rows[0][0])
            else:
                existing = await query(
                    "SELECT id FROM jobs WHERE user_id = %s AND idempotency_key = %s",
                    (user_id, idempotency_key),
                )
                if existing:
                    job_id = str(existing[0][0])
        else:
            await execute(
                "INSERT INTO jobs (id, user_id, kind, payload, max_attempts) "
                "VALUES (%s, %s, %s, %s, %s)",
                (job_id, user_id, kind, payload_json, max_attempts),
            )
        self._wake.set()
        return job_id

    async def get(self, job_id: str, user_id: int | None = None) -> dict | None:
        sql = (
            "SELECT id, user_id, kind, payload, status, progress, step, result, error, "
            "attempts, max_attempts, cancel_requested, created_at, started_at, finished_at "
            "FROM jobs WHERE id = %s"
        )
        params: tuple = (job_id,)
        if user_id is not None:
            sql += " AND user_id = %s"
            params = (job_id, user_id)
        rows = await query(sql, params)
        if not rows:
            return None
        return _job_dict(rows[0])

    async def list(self, user_id: int, limit: int = 30) -> list[dict]:
        rows = await query(
            "SELECT id, user_id, kind, payload, status, progress, step, result, error, "
            "attempts, max_attempts, cancel_requested, created_at, started_at, finished_at "
            "FROM jobs WHERE user_id = %s ORDER BY created_at DESC LIMIT %s",
            (user_id, max(1, min(limit, 100))),
        )
        return [_job_dict(r) for r in rows]

    async def cancel(self, job_id: str, user_id: int | None = None) -> dict | None:
        owner_sql = " AND user_id = %s" if user_id is not None else ""
        params: tuple = (job_id, user_id) if user_id is not None else (job_id,)
        rows = await execute(
            "UPDATE jobs SET cancel_requested = TRUE, "
            "status = CASE WHEN status = 'queued' THEN 'canceled' ELSE status END, "
            "finished_at = CASE WHEN status = 'queued' THEN now() ELSE finished_at END "
            f"WHERE id = %s AND status IN ('queued', 'running'){owner_sql} "
            "RETURNING status",
            params,
        )
        if not rows:
            return await self.get(job_id, user_id)
        status = rows[0][0]
        if status == "running":
            # Stop Docker containers that belong to this job in the background:
            # the API must return immediately, while the handler observes the
            # cancel flag at its next checkpoint.
            try:
                from app.core.sandbox.runtime import kill_job_containers
                asyncio.create_task(kill_job_containers(job_id))
            except Exception as exc:  # noqa: BLE001
                logger.warning("job_container_kill_failed", job_id=job_id, error=str(exc))
        self._wake.set()
        return await self.get(job_id, user_id)

    async def retry(self, job_id: str, user_id: int | None = None) -> dict | None:
        """Requeue a failed or canceled job with a fresh attempt budget."""
        owner_sql = " AND user_id = %s" if user_id is not None else ""
        params: tuple = (job_id, user_id) if user_id is not None else (job_id,)
        rows = await execute(
            "UPDATE jobs SET status = 'queued', attempts = 0, progress = 0, step = NULL, "
            "result = NULL, error = NULL, cancel_requested = FALSE, started_at = NULL, "
            "finished_at = NULL, heartbeat_at = NULL "
            f"WHERE id = %s AND status IN ('failed', 'canceled'){owner_sql} "
            "RETURNING id",
            params,
        )
        if not rows:
            return await self.get(job_id, user_id)
        self._wake.set()
        return await self.get(job_id, user_id)

    async def is_cancel_requested(self, job_id: str) -> bool:
        rows = await query(
            "SELECT cancel_requested, status FROM jobs WHERE id = %s", (job_id,)
        )
        if not rows:
            return True
        return bool(rows[0][0]) or rows[0][1] == "canceled"

    async def update_job(
        self, job_id: str, *, progress: float | None = None, step: str | None = None
    ) -> None:
        sets = ["heartbeat_at = now()"]
        params: list = []
        if progress is not None:
            sets.append("progress = %s")
            params.append(max(0.0, min(1.0, float(progress))))
        if step is not None:
            sets.append("step = %s")
            params.append(str(step)[:500])
        params.append(job_id)
        await execute(
            f"UPDATE jobs SET {', '.join(sets)} WHERE id = %s AND status = 'running'",
            tuple(params),
        )

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------
    async def _recover_stale(self) -> None:
        rows = await execute(
            "UPDATE jobs SET status = 'queued', started_at = NULL, heartbeat_at = NULL, "
            "error = 'worker restarted; job requeued' "
            "WHERE status = 'running' AND (heartbeat_at IS NULL OR "
            "heartbeat_at < now() - make_interval(secs => %s)) RETURNING id",
            (settings.job_stale_seconds,),
        )
        if rows:
            logger.info("stale_jobs_requeued", count=len(rows))

    async def _loop(self) -> None:
        while self._running:
            claimed = None
            try:
                claimed = await self._claim_one()
            except Exception as exc:  # noqa: BLE001
                logger.warning("job_claim_failed", error=str(exc))
            if claimed:
                self._spawn(claimed)
                continue
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                pass
            self._wake.clear()

    async def _claim_one(self) -> Job | None:
        available = [
            kind
            for kind, spec in self._handlers.items()
            if self._active_kinds.get(kind, 0) < spec.concurrency
        ]
        if not available:
            return None
        rows = await execute(
            """
            UPDATE jobs SET status = 'running', started_at = now(),
                heartbeat_at = now(), attempts = attempts + 1, error = NULL
            WHERE id = (
                SELECT id FROM jobs
                WHERE status = 'queued' AND cancel_requested = FALSE
                  AND kind = ANY(%s)
                ORDER BY created_at
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            RETURNING id, user_id, kind, payload, attempts, max_attempts
            """,
            (available,),
        )
        if not rows:
            return None
        r = rows[0]
        payload = r[3] or {}
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                payload = {}
        return Job(
            id=str(r[0]), user_id=r[1], kind=r[2], payload=payload,
            attempts=int(r[4] or 1), max_attempts=int(r[5] or 1),
        )

    def _spawn(self, job: Job) -> None:
        spec = self._handlers.get(job.kind)
        if not spec:
            return
        self._active_kinds[job.kind] = self._active_kinds.get(job.kind, 0) + 1
        task = asyncio.create_task(self._run(job, spec.fn), name=f"nova-job-{job.id}")
        self._active[job.id] = task

        def _done(_: asyncio.Task) -> None:
            self._active.pop(job.id, None)
            self._active_kinds[job.kind] = max(0, self._active_kinds.get(job.kind, 1) - 1)
            self._wake.set()

        task.add_done_callback(_done)

    async def _run(self, job: Job, handler: Handler) -> None:
        ctx = JobContext(job=job, runner=self)
        try:
            result = await handler(ctx)
            if await self.is_cancel_requested(job.id):
                raise JobCanceled()
            await execute(
                "UPDATE jobs SET status = 'succeeded', progress = 1, result = %s, "
                "error = NULL, finished_at = now(), heartbeat_at = now() "
                "WHERE id = %s AND status = 'running'",
                (json.dumps(result or {}, ensure_ascii=False), job.id),
            )
            logger.info("job_succeeded", job_id=job.id, kind=job.kind)
        except JobCanceled:
            await execute(
                "UPDATE jobs SET status = 'canceled', error = 'canceled by user', "
                "finished_at = now() WHERE id = %s",
                (job.id,),
            )
            logger.info("job_canceled", job_id=job.id, kind=job.kind)
        except asyncio.CancelledError:
            # Graceful shutdown: stop() requeues the row after we return.
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("job_failed", job_id=job.id, kind=job.kind)
            detail = f"{type(exc).__name__}: {exc}"[:2000]
            if job.attempts < job.max_attempts:
                await execute(
                    "UPDATE jobs SET status = 'queued', started_at = NULL, "
                    "heartbeat_at = NULL, error = %s WHERE id = %s",
                    (detail, job.id),
                )
            else:
                await execute(
                    "UPDATE jobs SET status = 'failed', error = %s, finished_at = now() "
                    "WHERE id = %s",
                    (detail, job.id),
                )

    async def _heartbeat_loop(self) -> None:
        while self._running:
            await asyncio.sleep(2)
            ids = list(self._active)
            if not ids:
                continue
            try:
                await execute(
                    "UPDATE jobs SET heartbeat_at = now() "
                    "WHERE id = ANY(%s::uuid[]) AND status = 'running'",
                    (ids,),
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("job_heartbeat_failed", error=str(exc))


def _job_dict(r: tuple) -> dict:
    def iso(value):
        return value.isoformat() if hasattr(value, "isoformat") else value

    return {
        "id": str(r[0]), "user_id": r[1], "kind": r[2], "payload": r[3] or {},
        "status": r[4], "progress": float(r[5] or 0), "step": r[6],
        "result": r[7] or {}, "error": r[8],
        "attempts": int(r[9] or 0), "max_attempts": int(r[10] or 1),
        "cancel_requested": bool(r[11]),
        "created_at": iso(r[12]), "started_at": iso(r[13]), "finished_at": iso(r[14]),
    }


# Process-wide runner.  The FastAPI lifespan starts/stops it.
runner = JobRunner()

"""In-process harness: patch external seams and drive the real agent loop."""
from __future__ import annotations

import copy
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.core import reflection as reflection_mod
from app.core import skills as skills_mod
from app.core.agent import evidence as evidence_mod
from app.core.agent import loop as loop_mod
from app.core.editing import service as edit_service
from app.core.indexing import pipeline as pipeline_mod
from app.core.jobs import service as jobs_service
from app.core.memory import facts as facts_mod
from app.core.memory import session as session_mod
from app.core.tools import base as tools_base
from app.core.tools import edit_file as edit_file_mod
from app.core.tools import get_registry as real_get_registry
from app.core.tools import write_files as write_files_mod
from evals.executors import ScriptedExecutor
from evals.fixtures import EVAL_PNG_BYTES, FixtureRepo
from evals.models import EvalRun, EvalTask, ToolCallRecord

USER = {"id": 1, "username": "eval", "role": "admin"}


class RecordingRegistry:
    """Transparent registry proxy that records every tool result."""

    def __init__(self, inner, records: list[ToolCallRecord]):
        self._inner = inner
        self.records = records

    def __getattr__(self, name: str):
        return getattr(self._inner, name)

    async def execute(self, name: str, args: dict, ctx) -> dict:
        result = await self._inner.execute(name, args, ctx)
        self.records.append(ToolCallRecord(
            id=str(getattr(ctx, "tool_call_id", "") or f"call-{len(self.records) + 1}"),
            name=name,
            args=dict(args) if isinstance(args, dict) else {},
            ok=bool(result.get("ok")),
            error=result.get("error"),
            error_class=result.get("error_class"),
            output=result.get("output"),
        ))
        return result


class InProcessHarness:
    def __init__(
        self,
        task: EvalTask,
        repo: FixtureRepo,
        executor,
        *,
        history: list[dict] | None = None,
    ):
        self.task = task
        self.repo = repo
        self.executor = executor
        self.history = copy.deepcopy(
            list(history if history is not None else task.history)
        )
        self.records: list[ToolCallRecord] = []
        self._patchers = []

    def _patch(self, obj, attr: str, value) -> None:
        patcher = patch.object(obj, attr, value)
        patcher.start()
        self._patchers.append(patcher)

    async def _fake_create_edit(
        self,
        *,
        user_id,
        session_id,
        repo_id,
        files,
        note="",
        mode="ask",
    ) -> dict:
        root = Path(self.repo.root)
        changes = edit_service.validate_changes(files)
        if not changes:
            raise ValueError("没有有效文件内容（检查路径与内容）")
        base = edit_service._read_current(root, changes)
        edit_service.assert_changes_preserve_tests(changes, base)
        diff = edit_service.build_diff(base, changes)
        applied = mode in ("auto", "full")
        if applied:
            edit_service._write_files(root, changes)
        return {
            "id": f"eval-edit-{len(self.records) + 1}",
            "status": "applied" if applied else "pending",
            "staged": not applied,
            "repo_id": str(repo_id),
            "repo_name": "eval-fixture",
            "files": list(changes),
            "diff": diff,
            "note": note,
        }

    def __enter__(self):
        window = (
            self.task.context_window
            or getattr(self.executor, "context_window", None)
            or 131_072
        )

        async def _get_llm(*_args, **_kwargs):
            return self.executor

        async def _load_vision_images(_user_id, _attachments):
            images = []
            for item in self.task.attachments:
                if str(item.get("mime") or "").lower() != "image/png":
                    continue
                images.append({
                    "id": str(item.get("id") or "eval-image"),
                    "filename": item.get("filename") or "pixel.png",
                    "mime": "image/png",
                    "data": EVAL_PNG_BYTES,
                })
            return images, []

        async def _get_repo(repo_id, _user_id):
            if str(repo_id) != self.repo.repo_id:
                return None
            return {
                "id": self.repo.repo_id,
                "name": "eval-fixture",
                "root_path": str(self.repo.root),
                "rules": "",
            }

        self._patch(loop_mod, "get_llm", _get_llm)
        self._patch(loop_mod, "retrieve", AsyncMock(return_value=[]))
        self._patch(
            session_mod, "recent_messages",
            AsyncMock(return_value=copy.deepcopy(self.history)),
        )
        self._patch(session_mod, "add_message", AsyncMock(return_value=1))
        self._patch(session_mod, "count_messages_since", AsyncMock(return_value=0))
        self._patch(facts_mod, "get_relevant_facts", AsyncMock(return_value=[]))
        self._patch(facts_mod, "extract_facts_from_turn", AsyncMock(return_value=0))
        self._patch(loop_mod, "log_audit", AsyncMock())
        self._patch(loop_mod, "trace_record", AsyncMock())
        self._patch(loop_mod, "_record_usage", AsyncMock())
        self._patch(loop_mod, "local_agent_online", AsyncMock(return_value=False))
        self._patch(loop_mod, "ensure_token_budget", AsyncMock())
        self._patch(loop_mod, "resolve_context_window", lambda _user_id, _llm=None: int(window))
        self._patch(loop_mod, "load_vision_images", _load_vision_images)
        self._patch(
            loop_mod, "get_registry",
            lambda: RecordingRegistry(real_get_registry(), self.records),
        )
        self._patch(tools_base, "log_audit", AsyncMock())
        self._patch(jobs_service, "enqueue_index", AsyncMock(return_value="eval-job"))
        self._patch(
            jobs_service, "enqueue_session_summary",
            AsyncMock(return_value="eval-job"),
        )
        self._patch(jobs_service, "is_running", lambda: False)
        self._patch(evidence_mod, "verify_citations", AsyncMock(return_value={
            "executed": False, "citations": [], "verified": 0,
            "missing": 0, "out_of_range": 0, "skipped": 0,
        }))
        self._patch(reflection_mod, "lessons_for_context", AsyncMock(return_value=[]))
        self._patch(reflection_mod, "record_outcome", AsyncMock())
        self._patch(skills_mod, "build_skill_prompt", lambda _message: "")
        self._patch(edit_file_mod, "create_edit", self._fake_create_edit)
        self._patch(write_files_mod, "create_edit", self._fake_create_edit)

        original_get_repo = pipeline_mod.get_repo
        for module in list(sys.modules.values()):
            if module is not None and getattr(module, "get_repo", None) is original_get_repo:
                self._patch(module, "get_repo", _get_repo)
        return self

    def __exit__(self, exc_type, exc, tb):
        for patcher in reversed(self._patchers):
            patcher.stop()
        self._patchers.clear()
        return False

    @staticmethod
    def _consume(event: dict, run: EvalRun) -> None:
        name = event.get("event")
        data = event.get("data") or {}
        if name == "token":
            run.final_text += str(data.get("text") or "")
        elif name == "usage":
            run.usage = data
        elif name == "done":
            run.rounds = int(data.get("rounds") or 0)

    async def run(self) -> EvalRun:
        started = time.perf_counter()
        run = EvalRun(task=self.task, repo=self.repo)
        session = {
            "id": "eval-session",
            "title": "eval",
            "permission_mode": self.task.permission_mode,
            "repo_ids": [self.repo.repo_id],
            "model": "eval-model",
            "summary": "",
            "summary_upto_id": 0,
            "llm_overrides": (
                {} if self.task.context_window is None
                else {"context_window": self.task.context_window}
            ),
        }
        try:
            async for event in loop_mod.run_chat(
                USER,
                session,
                self.task.prompt,
                [self.repo.repo_id],
                attachments=[dict(item) for item in self.task.attachments],
            ):
                run.events.append(event)
                self._consume(event, run)
        except Exception as exc:  # noqa: BLE001 — surfaced as eval error
            run.error = f"{type(exc).__name__}: {exc}"
        run.tool_calls = list(self.records)
        run.llm_messages = list(getattr(self.executor, "llm_messages", []))
        run.duration_ms = int((time.perf_counter() - started) * 1000)
        return run

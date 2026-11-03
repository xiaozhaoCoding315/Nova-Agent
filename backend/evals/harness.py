"""In-process harness: patch external seams and drive the real agent loop."""
from __future__ import annotations

import copy
import sys
import time
import uuid
from contextlib import aclosing
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.core import reflection as reflection_mod
from app.core import skills as skills_mod
from app.core import trace as trace_mod
from app.core.agent import evidence as evidence_mod
from app.core.agent import loop as loop_mod
from app.core.editing import service as edit_service
from app.core.indexing import pipeline as pipeline_mod
from app.core.indexing import symbols as symbols_mod
from app.core.jobs import service as jobs_service
from app.core.llm import factory as llm_factory_mod
from app.core.llm import usage as usage_mod
from app.core.memory import facts as facts_mod
from app.core.memory import session as session_mod
from app.core.rag import retriever as retriever_mod
from app.core.security import audit as audit_mod
from app.core.security import limits as limits_mod
from app.core.security.paths import is_secret_path, try_normalize_relpath
from app.core.tools import base as tools_base
from app.core.tools import edit_file as edit_file_mod
from app.core.tools import get_registry as real_get_registry
from app.core.tools import write_files as write_files_mod
from evals.fixtures import EVAL_PNG_BYTES, FixtureRepo
from evals.models import EvalRun, EvalTask, ToolCallRecord

USER = {"id": 1, "username": "eval", "role": "admin"}

EMPTY_CITATIONS = {
    "executed": False, "citations": [], "verified": 0,
    "missing": 0, "out_of_range": 0, "skipped": 0,
}


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

    def _patch_bindings(self, name: str, original, replacement) -> None:
        """Patch every loaded module attribute still bound to ``original``.

        Tools bind shared seams into their own modules at import time
        (``search_code.search_symbols``, ``run_command.log_audit``, ...), so
        patching only the defining module would leave those call sites
        reaching the real PostgreSQL / Qdrant / provider clients.
        """
        for module in list(sys.modules.values()):
            if module is None:
                continue
            try:
                current = getattr(module, name, None)
            except Exception:  # noqa: BLE001 — unusual module __getattr__
                current = None
            if current is replacement:
                continue
            if current is original:
                self._patch(module, name, replacement)

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
        if str(repo_id) != self.repo.repo_id:
            raise ValueError("仓库不存在或无权访问")
        for raw_path in (files or {}):
            candidate = try_normalize_relpath(raw_path)
            if candidate and is_secret_path(candidate):
                raise ValueError(f"拒绝写入密钥/凭据文件：{candidate}")
        root = Path(self.repo.root).resolve()
        changes = edit_service.validate_changes(files)
        if not changes:
            raise ValueError("没有有效文件内容（检查路径与内容）")
        base = edit_service._read_current(root, changes)
        edit_service.assert_changes_preserve_tests(changes, base)
        diff = edit_service.build_diff(base, changes)
        edit_id = str(uuid.uuid4())
        applied = mode in ("auto", "full")
        if applied:
            edit_service._write_files(root, changes)
        return {
            "id": edit_id,
            "status": "applied" if applied else "pending",
            "staged": not applied,
            "repo_id": str(repo_id),
            "repo_name": "eval-fixture",
            "files": list(changes),
            "diff": diff,
            "note": note,
        }

    def __enter__(self):
        try:
            self._start()
        except BaseException:
            self.__exit__(*sys.exc_info())
            raise
        return self

    def _start(self) -> None:
        window = (
            self.task.context_window
            or getattr(self.executor, "context_window", None)
            or 131_072
        )

        fake_retrieve = AsyncMock(return_value=[])
        fake_log_audit = AsyncMock()
        fake_trace_record = AsyncMock()
        fake_record_usage = AsyncMock()
        fake_ensure_token_budget = AsyncMock()
        fake_verify_citations = AsyncMock(return_value=dict(EMPTY_CITATIONS))
        fake_search_symbols = AsyncMock(return_value=[])

        # Save the real functions before any patching; the identity scans
        # below must compare against the originals, not our replacements.
        original_get_repo = pipeline_mod.get_repo
        original_retrieve = retriever_mod.retrieve
        original_get_llm = llm_factory_mod.get_llm
        original_log_audit = audit_mod.log_audit
        original_trace_record = trace_mod.record
        original_record_usage = usage_mod.record_usage
        original_ensure_token_budget = limits_mod.ensure_token_budget
        original_verify_citations = evidence_mod.verify_citations
        original_search_symbols = symbols_mod.search_symbols

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
        self._patch(loop_mod, "retrieve", fake_retrieve)
        self._patch(
            session_mod, "recent_messages",
            AsyncMock(return_value=copy.deepcopy(self.history)),
        )
        self._patch(session_mod, "add_message", AsyncMock(return_value=1))
        self._patch(session_mod, "count_messages_since", AsyncMock(return_value=0))
        self._patch(facts_mod, "get_relevant_facts", AsyncMock(return_value=[]))
        self._patch(facts_mod, "extract_facts_from_turn", AsyncMock(return_value=0))
        self._patch(loop_mod, "log_audit", fake_log_audit)
        self._patch(loop_mod, "trace_record", fake_trace_record)
        self._patch(loop_mod, "_record_usage", AsyncMock())
        self._patch(loop_mod, "local_agent_online", AsyncMock(return_value=False))
        self._patch(loop_mod, "ensure_token_budget", fake_ensure_token_budget)
        self._patch(loop_mod, "resolve_context_window", lambda _user_id, _llm=None: int(window))
        self._patch(loop_mod, "load_vision_images", _load_vision_images)
        self._patch(
            loop_mod, "get_registry",
            lambda: RecordingRegistry(real_get_registry(), self.records),
        )
        self._patch(tools_base, "log_audit", fake_log_audit)
        self._patch(jobs_service, "enqueue_index", AsyncMock(return_value="eval-job"))
        self._patch(
            jobs_service, "enqueue_session_summary",
            AsyncMock(return_value="eval-job"),
        )
        self._patch(jobs_service, "is_running", lambda: False)
        self._patch(evidence_mod, "verify_citations", fake_verify_citations)
        self._patch(reflection_mod, "lessons_for_context", AsyncMock(return_value=[]))
        self._patch(reflection_mod, "record_outcome", AsyncMock())
        self._patch(skills_mod, "build_skill_prompt", lambda _message: "")
        self._patch(edit_file_mod, "create_edit", self._fake_create_edit)
        self._patch(write_files_mod, "create_edit", self._fake_create_edit)

        # Direct-patch each defining module, then every module that imported
        # the same function object.  The tool modules bind these seams at
        # import time, so a defining-module-only patch is not enough.
        self._patch(pipeline_mod, "get_repo", _get_repo)
        self._patch_bindings("get_repo", original_get_repo, _get_repo)
        self._patch(retriever_mod, "retrieve", fake_retrieve)
        self._patch_bindings("retrieve", original_retrieve, fake_retrieve)
        self._patch(llm_factory_mod, "get_llm", _get_llm)
        self._patch_bindings("get_llm", original_get_llm, _get_llm)
        self._patch(audit_mod, "log_audit", fake_log_audit)
        self._patch_bindings("log_audit", original_log_audit, fake_log_audit)
        self._patch(trace_mod, "record", fake_trace_record)
        self._patch_bindings("trace_record", original_trace_record, fake_trace_record)
        self._patch(usage_mod, "record_usage", fake_record_usage)
        self._patch_bindings("record_usage", original_record_usage, fake_record_usage)
        self._patch(limits_mod, "ensure_token_budget", fake_ensure_token_budget)
        self._patch_bindings(
            "ensure_token_budget", original_ensure_token_budget,
            fake_ensure_token_budget,
        )
        self._patch_bindings(
            "verify_citations", original_verify_citations, fake_verify_citations,
        )
        self._patch(symbols_mod, "search_symbols", fake_search_symbols)
        self._patch_bindings(
            "search_symbols", original_search_symbols, fake_search_symbols,
        )

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
        elif name == "error":
            code = str(data.get("code") or "error")
            message = str(data.get("message") or "")
            run.error = f"{code}: {message}" if message else code

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
            async with aclosing(loop_mod.run_chat(
                USER,
                session,
                self.task.prompt,
                [self.repo.repo_id],
                attachments=[dict(item) for item in self.task.attachments],
                persist_on_cancel=True,
            )) as events:
                async for event in events:
                    run.events.append(event)
                    self._consume(event, run)
        except Exception as exc:  # noqa: BLE001 — surfaced as eval error
            run.error = f"{type(exc).__name__}: {exc}"
        run.tool_calls = list(self.records)
        run.llm_messages = copy.deepcopy(
            list(getattr(self.executor, "llm_messages", []))
        )
        run.duration_ms = int((time.perf_counter() - started) * 1000)
        return run

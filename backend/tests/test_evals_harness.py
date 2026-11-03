"""Harness patching, recording, and one end-to-end scripted turn."""
import asyncio

import pytest

import app.core.tools.diagnostics as diagnostics_mod
import app.core.tools.install_deps as install_deps_mod
import app.core.tools.local_exec as local_exec_mod
import app.core.tools.run_code as run_code_mod
import app.core.tools.run_command as run_command_mod
import app.core.tools.search_code as search_code_mod
import app.db as db_mod
from app.core.agent import subagent as subagent_mod
from app.core.indexing import pipeline as pipeline_mod
from app.core.memory import session as session_mod
from app.core.tools import write_files as write_files_mod
from evals.executors import ScriptedExecutor
from evals.fixtures import create_fixture
from evals.harness import InProcessHarness, RecordingRegistry
from evals.models import EvalTask


def _task(script, checks=(), context_window=None, attachments=()):
    return EvalTask(
        id="harness_task",
        mode="scripted",
        category="test",
        description="",
        prompt="读取 calc.py 并回答。",
        fixture="python_small",
        checks=checks,
        script=script,
        context_window=context_window,
        attachments=attachments,
    )


class _FakeRegistry:
    def __init__(self, result):
        self.result = result

    def get(self, name):
        return None

    async def execute(self, name, args, ctx):
        return self.result


@pytest.mark.asyncio
async def test_recording_registry_records_success_and_policy_denial():
    records = []
    inner = _FakeRegistry({"ok": True, "output": {"content": "x"}, "ms": 1})
    registry = RecordingRegistry(inner, records)

    class _Ctx:
        tool_call_id = "call-1"

    result = await registry.execute("read_file", {"path": "calc.py"}, _Ctx())
    assert result is inner.result
    assert result["ok"] is True
    assert records[0].name == "read_file"
    assert records[0].ok is True
    assert records[0].error_class is None

    inner.result = {
        "ok": False, "error": "path escapes repo", "error_class": "business", "ms": 0,
    }
    result = await registry.execute("read_file", {"path": "../x"}, _Ctx())
    assert result["ok"] is False
    assert records[1].error_class == "business"

    inner.result = {
        "ok": False, "error": "readonly", "error_class": "policy", "ms": 0,
    }
    result = await registry.execute("edit_file", {}, _Ctx())
    assert result["ok"] is False
    assert records[2].error_class == "policy"


@pytest.mark.asyncio
async def test_harness_runs_a_plain_answer_without_external_services():
    task = _task((
        (
            {"type": "content", "content": "done"},
            {"type": "finish", "finish_reason": "stop"},
        ),
    ))
    repo = create_fixture("python_small")
    try:
        with InProcessHarness(task, repo, ScriptedExecutor(task.script)) as harness:
            run = await harness.run()
        assert run.error is None
        assert run.final_text == "done"
        assert run.rounds == 1
        assert run.llm_messages
        assert run.tool_calls == []
    finally:
        repo.cleanup()


@pytest.mark.asyncio
async def test_harness_repo_resolver_reaches_module_level_imports():
    task = _task((
        (
            {"type": "tool_calls", "tool_calls": [{
                "id": "call-1", "name": "read_file",
                "arguments": '{"path": "calc.py"}',
            }]},
            {"type": "finish", "finish_reason": "tool_calls"},
        ),
        (
            {"type": "content", "content": "看到 a - b"},
            {"type": "finish", "finish_reason": "stop"},
        ),
    ))
    repo = create_fixture("python_small")
    try:
        with InProcessHarness(task, repo, ScriptedExecutor(task.script)) as harness:
            run = await harness.run()
        assert run.error is None
        assert run.tool_calls[0].name == "read_file"
        assert run.tool_calls[0].ok is True
        assert run.tool_calls[0].output["content"].startswith("def add")
    finally:
        repo.cleanup()


@pytest.mark.asyncio
async def test_harness_restores_get_repo_after_exit():
    task = _task(())
    repo = create_fixture("python_small")
    original = pipeline_mod.get_repo
    try:
        with InProcessHarness(task, repo, ScriptedExecutor(task.script)):
            assert pipeline_mod.get_repo is not original
        assert pipeline_mod.get_repo is original
    finally:
        repo.cleanup()


@pytest.mark.asyncio
async def test_fake_create_edit_applies_in_auto_and_stages_in_ask():
    task = _task(())
    repo = create_fixture("python_small")
    try:
        with InProcessHarness(task, repo, ScriptedExecutor(task.script)):
            auto = await write_files_mod.create_edit(
                user_id=1,
                session_id="eval-session",
                repo_id="eval-repo",
                files={"new.txt": "hello"},
                mode="auto",
            )
            staged = await write_files_mod.create_edit(
                user_id=1,
                session_id="eval-session",
                repo_id="eval-repo",
                files={"staged.txt": "nope"},
                mode="ask",
            )
        assert auto["staged"] is False
        assert (repo.root / "new.txt").read_text(encoding="utf-8") == "hello"
        assert staged["staged"] is True
        assert not (repo.root / "staged.txt").exists()
    finally:
        repo.cleanup()


@pytest.mark.asyncio
async def test_fake_create_edit_matches_real_repo_and_secret_checks():
    task = _task(())
    repo = create_fixture("python_small")
    try:
        with InProcessHarness(task, repo, ScriptedExecutor(task.script)):
            edit_one = await write_files_mod.create_edit(
                user_id=1,
                session_id="eval-session",
                repo_id="eval-repo",
                files={"one.txt": "1"},
                mode="auto",
            )
            edit_two = await write_files_mod.create_edit(
                user_id=1,
                session_id="eval-session",
                repo_id="eval-repo",
                files={"two.txt": "2"},
                mode="auto",
            )
            with pytest.raises(ValueError, match="仓库不存在或无权访问"):
                await write_files_mod.create_edit(
                    user_id=1,
                    session_id="eval-session",
                    repo_id="other-repo",
                    files={"nope.txt": "x"},
                    mode="auto",
                )
            with pytest.raises(ValueError, match="拒绝写入密钥/凭据文件"):
                await write_files_mod.create_edit(
                    user_id=1,
                    session_id="eval-session",
                    repo_id="eval-repo",
                    files={".env": "SECRET=1"},
                    mode="auto",
                )
        assert edit_one["id"] != edit_two["id"]
        assert not (repo.root / "nope.txt").exists()
        assert not (repo.root / ".env").exists()
    finally:
        repo.cleanup()


@pytest.mark.asyncio
async def test_harness_search_code_tool_stays_off_the_database(monkeypatch):
    task = _task((
        (
            {"type": "tool_calls", "tool_calls": [{
                "id": "call-1", "name": "search_code",
                "arguments": '{"query": "add"}',
            }]},
            {"type": "finish", "finish_reason": "tool_calls"},
        ),
        (
            {"type": "content", "content": "没有命中"},
            {"type": "finish", "finish_reason": "stop"},
        ),
    ))
    db_calls = []

    async def _unexpected_db_call(*args, **kwargs):
        db_calls.append(args)
        raise AssertionError("search_code reached PostgreSQL")

    monkeypatch.setattr(db_mod, "query", _unexpected_db_call)
    monkeypatch.setattr(db_mod, "execute", _unexpected_db_call)

    repo = create_fixture("python_small")
    try:
        with InProcessHarness(task, repo, ScriptedExecutor(task.script)) as harness:
            run = await harness.run()
        assert db_calls == []
        assert run.error is None
        assert not [e for e in run.events if e.get("event") == "error"]
        assert run.tool_calls and run.tool_calls[0].name == "search_code"
        assert run.tool_calls[0].ok is True
        assert run.tool_calls[0].output["symbols"] == []
        assert run.tool_calls[0].output["snippets"] == []
    finally:
        repo.cleanup()


def test_harness_patches_tool_binding_sites_and_restores_them():
    binding_sites = (
        (search_code_mod, "retrieve"),
        (search_code_mod, "search_symbols"),
        (subagent_mod, "get_llm"),
        (subagent_mod, "ensure_token_budget"),
        (subagent_mod, "record_usage"),
        (subagent_mod, "trace_record"),
        (subagent_mod, "verify_citations"),
        (run_command_mod, "log_audit"),
        (diagnostics_mod, "log_audit"),
        (install_deps_mod, "log_audit"),
        (local_exec_mod, "log_audit"),
        (run_code_mod, "log_audit"),
    )
    originals = [
        (module, attr, getattr(module, attr)) for module, attr in binding_sites
    ]
    task = _task(())
    repo = create_fixture("python_small")
    try:
        with InProcessHarness(task, repo, ScriptedExecutor(task.script)):
            for module, attr, original in originals:
                assert getattr(module, attr) is not original, attr
        for module, attr, original in originals:
            assert getattr(module, attr) is original, attr
    finally:
        repo.cleanup()


@pytest.mark.asyncio
async def test_harness_snapshots_executor_messages_by_value():
    task = _task((
        (
            {"type": "content", "content": "done"},
            {"type": "finish", "finish_reason": "stop"},
        ),
    ))
    repo = create_fixture("python_small")
    executor = ScriptedExecutor(task.script)
    try:
        with InProcessHarness(task, repo, executor) as harness:
            run = await harness.run()
        assert run.llm_messages
        executor.llm_messages[0].append(
            {"role": "user", "content": "late mutation"}
        )
        assert run.llm_messages[0][-1] != {"role": "user", "content": "late mutation"}
        run.llm_messages[0][0]["content"] = "mutated snapshot"
        assert executor.llm_messages[0][0]["content"] != "mutated snapshot"
    finally:
        repo.cleanup()


@pytest.mark.asyncio
async def test_harness_records_loop_error_event_in_run_error():
    task = _task(())
    repo = create_fixture("python_small")
    try:
        with InProcessHarness(task, repo, ScriptedExecutor(task.script)) as harness:
            run = await harness.run()
        assert any(e.get("event") == "error" for e in run.events)
        assert run.error is not None
        assert run.error.startswith("llm_error:")
    finally:
        repo.cleanup()


@pytest.mark.asyncio
async def test_harness_cancellation_persists_before_propagating():
    order = []

    class _BlockingExecutor:
        supports_vision = False
        context_window = 131_072

        def __init__(self):
            self.llm_messages = []

        async def astream_with_tools(self, messages, tools):
            self.llm_messages.append(messages)
            yield {"type": "content", "content": "部分回答"}
            await asyncio.Event().wait()

    async def _persist(*_args, **_kwargs):
        order.append("persisted")
        return 1

    task = _task(())
    repo = create_fixture("python_small")
    executor = _BlockingExecutor()
    try:
        with InProcessHarness(task, repo, executor) as harness:
            session_mod.add_message.side_effect = _persist

            async def _drive():
                try:
                    await harness.run()
                except asyncio.CancelledError:
                    order.append("cancelled")
                    raise

            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(_drive(), timeout=0.5)
        assert order[:2] == ["persisted", "cancelled"]
    finally:
        repo.cleanup()

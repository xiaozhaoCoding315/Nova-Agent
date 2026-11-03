"""Harness patching, recording, and one end-to-end scripted turn."""
import pytest

from app.core.indexing import pipeline as pipeline_mod
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

"""Change workflow: SPEC cleaning, plan validation, scope enforcement."""
from unittest.mock import AsyncMock

import pytest

from app.api.v1 import changes as changes_api
from app.core.changes import executor, service
from app.core.jobs.handlers import register_all
from app.core.jobs.runner import JobRunner


def test_clean_spec_trims_and_caps():
    spec = service.clean_spec({
        "title": "x" * 300,
        "goal": " 目标 ",
        "in_scope": ["a"] * 30,
        "acceptance_cases": ["pytest tests/test_a.py 通过"],
        "open_questions": ["是否兼容 Python 3.10？"],
    })
    assert len(spec["title"]) == 120
    assert spec["goal"] == "目标"
    assert len(spec["in_scope"]) == service.MAX_LIST_ITEMS
    assert spec["acceptance_cases"] == ["pytest tests/test_a.py 通过"]


def test_validate_plan_accepts_serial_dependencies():
    tasks, error = service.validate_plan({"tasks": [
        {
            "title": "新增接口", "kind": "feature",
            "in_scope": ["app/api"], "out_scope": ["tests/legacy"],
            "acceptance": "pytest tests/test_todo.py 通过", "depends_on": [],
        },
        {
            "title": "补测试", "kind": "test",
            "in_scope": ["tests"], "out_scope": [],
            "acceptance": "pytest tests/test_todo.py 通过", "depends_on": [1],
        },
    ]})
    assert error is None
    assert len(tasks) == 2
    assert tasks[1]["depends_on"] == [1]


@pytest.mark.parametrize("tasks,expected", [
    ([], "缺少任务"),
    ([{"title": "x", "kind": "feature", "acceptance": ""}], "缺少可判定验收"),
    ([{"title": "x", "kind": "deploy", "acceptance": "部署成功即可"}], "类型不支持"),
    ([
        {"title": "a", "kind": "feature", "acceptance": "pytest 通过"},
        {"title": "b", "kind": "feature", "acceptance": "pytest 通过", "depends_on": [2]},
    ], "只能依赖前面的任务"),
])
def test_validate_plan_rejects_invalid_plans(tasks, expected):
    _, error = service.validate_plan({"tasks": tasks})
    assert expected in error


def test_scope_error_allows_prefix_and_glob():
    assert executor.scope_error("app/main.py", ["app"], []) is None
    assert executor.scope_error("app/routers/todo.py", ["app/*.py"], []) is None
    assert "不在任务允许范围" in executor.scope_error("docs/readme.md", ["app"], [])
    assert "禁止修改范围" in executor.scope_error("tests/test_a.py", ["app", "tests"], ["tests"])


def test_validate_generated_files_enforces_scope_and_test_guard():
    current = {"app/main.py": "print(1)\n", "tests/test_a.py": "def test_a():\n    assert True\n"}

    changes, error = executor.validate_generated_files(
        {"app/main.py": "print(2)\n"}, current, ["app"], []
    )
    assert error is None and changes == {"app/main.py": "print(2)\n"}

    _, error = executor.validate_generated_files(
        {"docs/readme.md": "x"}, current, ["app"], []
    )
    assert "不在任务允许范围" in error

    _, error = executor.validate_generated_files(
        {"tests/test_a.py": "def test_b():\n    assert True\n"}, current, ["tests"], []
    )
    assert "删除了已有测试" in error


@pytest.mark.asyncio
async def test_approve_spec_requires_acceptance_and_no_open_questions(monkeypatch):
    draft = {
        "id": "c1", "status": "draft", "goal": "实现接口",
        "acceptance_cases": [], "open_questions": [],
    }
    monkeypatch.setattr(service, "get_change", AsyncMock(return_value=draft))
    with pytest.raises(ValueError, match="验收"):
        await service.approve_spec("c1", 1)

    draft["acceptance_cases"] = ["pytest 通过"]
    draft["open_questions"] = ["需要兼容旧接口吗？"]
    with pytest.raises(ValueError, match="澄清"):
        await service.approve_spec("c1", 1)

    draft["open_questions"] = []
    execute = AsyncMock()
    monkeypatch.setattr(service, "execute", execute)
    monkeypatch.setattr(
        service, "get_change",
        AsyncMock(side_effect=[draft, {**draft, "status": "approved"}]),
    )
    result = await service.approve_spec("c1", 1)
    assert result["status"] == "approved"
    sql, params = execute.await_args.args
    assert "status = 'approved'" in sql
    assert params == ("c1",)


def test_change_handlers_and_routes_registered():
    runner = JobRunner()
    register_all(runner)
    assert runner.has("change_spec")
    assert runner.has("change_plan")
    assert runner.has("change_execute")
    paths = {route.path for route in changes_api.router.routes}
    assert "/changes" in paths
    assert "/changes/{change_id}/approve" in paths
    assert "/changes/{change_id}/apply" in paths


@pytest.mark.asyncio
async def test_gate_runs_on_unwritten_overrides(monkeypatch):
    from app.core.verify import service as verify_service
    from app.core.verify.profiles import VerifyProfile, VerifyStep

    monkeypatch.setattr(
        verify_service, "_collect_repo_files",
        AsyncMock(return_value={"app/main.py": "old"}),
    )
    monkeypatch.setattr(
        verify_service, "detect_profile",
        lambda files: VerifyProfile(
            stack="python", steps=[VerifyStep("检查", "python -c pass")]
        ),
    )
    monkeypatch.setattr(
        verify_service, "sandbox_status",
        AsyncMock(return_value={"available": True, "builder_available": True}),
    )
    sandbox_execute = AsyncMock(return_value={
        "stdout": "ok", "stderr": "", "exit_code": 0, "timed_out": False,
    })
    monkeypatch.setattr(verify_service, "sandbox_execute", sandbox_execute)

    result = await verify_service.run_verification(
        {"id": "r1"}, {"id": 1}, overrides={"app/new.py": "print(1)"}
    )

    assert result["status"] == "passed"
    sent = sandbox_execute.await_args.kwargs["files"]
    assert sent["app/new.py"] == "print(1)"
    assert sent["app/main.py"] == "old"

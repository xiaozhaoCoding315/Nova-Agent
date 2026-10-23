"""Verification profiles and red-phase classification."""
from unittest.mock import AsyncMock

import pytest

from app.core.tasks.engine import _classify_red
from app.core.verify import service as verify_service
from app.core.verify.profiles import detect_profile


def test_python_profile_runs_compile_and_pytest():
    profile = detect_profile({
        "app/main.py": "print(1)",
        "tests/test_main.py": "def test_a(): pass",
    })
    commands = [step.command for step in profile.steps]
    assert profile.stack == "python"
    assert any("compileall" in cmd for cmd in commands)
    assert any("pytest" in cmd for cmd in commands)


def test_python_profile_without_tests_skips_pytest():
    profile = detect_profile({"app/main.py": "print(1)"})
    assert [step.name for step in profile.steps] == ["语法检查"]
    assert any("未发现测试" in note for note in profile.notes)


def test_ruff_and_mypy_are_only_added_when_configured():
    base = {"app/main.py": "print(1)", "tests/test_main.py": "def test_a(): pass"}
    plain = detect_profile(base)
    assert not any("ruff" in step.command or "mypy" in step.command for step in plain.steps)

    configured = detect_profile({
        **base,
        "ruff.toml": "line-length = 100",
        "mypy.ini": "[mypy]",
    })
    commands = [step.command for step in configured.steps]
    assert any("ruff" in cmd for cmd in commands)
    assert any("mypy" in cmd for cmd in commands)


def test_node_profile_runs_install_typecheck_test_build():
    profile = detect_profile({
        "package.json": """{
          "scripts": {"test": "node --test", "build": "node build.js"},
          "devDependencies": {"typescript": "^5.6.0"}
        }""",
        "package-lock.json": "{}",
        "tsconfig.json": "{}",
        "src/app.ts": "export const value: number = 1",
    })
    assert profile.stack == "node"
    assert not profile.unsupported_reason
    names = [step.name for step in profile.steps]
    assert "安装 Node 依赖" in names
    assert "类型检查（tsc）" in names
    assert "Node 测试" in names
    assert "构建（npm）" in names
    assert all(step.image == "node" for step in profile.steps)
    assert profile.steps[0].network is True


def test_node_profile_without_scripts_is_unsupported():
    profile = detect_profile({"package.json": "{}", "src/app.tsx": "export default 1"})
    assert profile.stack == "node"
    assert profile.unsupported_reason


def test_fullstack_profile_uses_both_images():
    profile = detect_profile({
        "app/main.py": "print(1)",
        "tests/test_main.py": "def test_a(): pass",
        "package.json": '{"scripts": {"test": "node --test", "build": "node build.js"}}',
    })
    assert profile.stack == "fullstack"
    assert {step.image for step in profile.steps} == {"builder", "node"}
    assert any("Python 与 Node" in note for note in profile.notes)


@pytest.mark.parametrize(
    "result, ok",
    [
        ({"exit_code": 1, "stdout": "AssertionError: boom"}, True),
        ({"exit_code": 0, "stdout": "1 passed"}, False),
        ({"exit_code": 2, "stdout": "ERROR collecting tests/test_x.py"}, False),
        ({"exit_code": 1, "stdout": "ModuleNotFoundError: no module"}, False),
        ({"exit_code": -1, "timed_out": True, "stdout": ""}, False),
    ],
)
def test_red_phase_classification(result, ok):
    assert _classify_red(result)[0] is ok


@pytest.mark.asyncio
async def test_run_verification_aggregates_steps(monkeypatch):
    monkeypatch.setattr(
        verify_service, "_collect_repo_files",
        AsyncMock(return_value={"app.py": "print(1)", "tests/test_app.py": "def test_a(): pass"}),
    )
    monkeypatch.setattr(
        verify_service, "sandbox_status",
        AsyncMock(return_value={"available": True, "builder_available": True}),
    )
    executed: list[str] = []

    async def fake_execute(**kwargs):
        executed.append(kwargs["command"])
        return {"exit_code": 0, "stdout": "ok", "stderr": "", "timed_out": False}

    monkeypatch.setattr(verify_service, "sandbox_execute", fake_execute)
    result = await verify_service.run_verification({"id": "r1"}, {"id": 1})

    assert result["status"] == "passed"
    assert result["stack"] == "python"
    assert [s["name"] for s in result["steps"]] == ["语法检查", "单元测试"]
    assert len(executed) == 2


@pytest.mark.asyncio
async def test_node_verification_uses_node_image_and_volume(monkeypatch):
    monkeypatch.setattr(
        verify_service, "_collect_repo_files",
        AsyncMock(return_value={
            "package.json": '{"scripts": {"test": "node --test", "build": "node build.js"}}',
        }),
    )
    monkeypatch.setattr(
        verify_service, "sandbox_status",
        AsyncMock(return_value={
            "available": True,
            "builder_available": True,
            "node_available": True,
        }),
    )
    calls: list[dict] = []

    async def fake_execute(**kwargs):
        calls.append(kwargs)
        return {"exit_code": 0, "stdout": "ok", "stderr": "", "timed_out": False}

    monkeypatch.setattr(verify_service, "sandbox_execute", fake_execute)
    result = await verify_service.run_verification({"id": "node-repo"}, {"id": 1, "role": "admin"})

    assert result["status"] == "passed"
    assert result["stack"] == "node"
    assert calls
    assert all(call["image"] == verify_service.settings.sandbox_node_image for call in calls)
    assert all(call["deps_mount"] == "/workspace/node_modules" for call in calls)
    assert all(call["deps_volume"].startswith("nova-node-deps-") for call in calls)


@pytest.mark.asyncio
async def test_node_verification_fails_honestly_without_image(monkeypatch):
    monkeypatch.setattr(
        verify_service, "_collect_repo_files",
        AsyncMock(return_value={"package.json": '{"scripts": {"test": "node --test"}}'}),
    )
    monkeypatch.setattr(
        verify_service, "sandbox_status",
        AsyncMock(return_value={"available": True, "builder_available": True, "node_available": False}),
    )
    monkeypatch.setattr(
        verify_service, "sandbox_execute",
        AsyncMock(return_value={"exit_code": 0, "stdout": "", "stderr": "", "timed_out": False}),
    )
    result = await verify_service.run_verification({"id": "r1"}, {"id": 1})
    assert result["status"] == "failed"
    assert any("node 镜像" in note for note in result["notes"])
    assert result["steps"][0]["status"] == "failed"

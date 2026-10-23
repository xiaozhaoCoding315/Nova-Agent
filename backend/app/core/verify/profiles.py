"""Stack-aware verification profiles.

Only deterministic, sandbox-runnable checks belong here. A profile describes
which commands to run and which are required; missing tooling is reported as
skipped instead of pretending verification passed.
"""
from dataclasses import dataclass, field

from app.core.security.test_guard import is_test_path


@dataclass(frozen=True)
class VerifyStep:
    name: str
    command: str
    required: bool = True
    timeout: int = 90


@dataclass(frozen=True)
class VerifyProfile:
    stack: str
    steps: list[VerifyStep] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    unsupported_reason: str = ""


def _has_python(files: list[str]) -> bool:
    return any(path.lower().endswith((".py", ".pyi")) for path in files)


def _has_tests(files: list[str]) -> bool:
    return any(is_test_path(path) for path in files)


def _read_optional(files: dict[str, str], name: str) -> str:
    for path, content in files.items():
        if path.lower() == name:
            return content
    return ""


def detect_profile(files: dict[str, str]) -> VerifyProfile:
    paths = list(files)
    has_node = any(path.lower().endswith(("package.json", "tsconfig.json")) for path in paths)
    has_python = _has_python(paths)

    if not has_python:
        if has_node:
            return VerifyProfile(
                stack="node",
                notes=["检测到 Node/前端项目；当前验证镜像只支持 Python 运行时"],
                unsupported_reason="Node/前端项目暂不支持沙箱验证（P2 计划）",
            )
        return VerifyProfile(stack="unknown", unsupported_reason="未检测到可验证的 Python 项目")

    steps = [VerifyStep("语法检查", "python -m compileall -q .", required=True, timeout=60)]
    notes: list[str] = []

    if _has_tests(paths):
        steps.append(VerifyStep("单元测试", "python -m pytest -q", required=True, timeout=120))
    else:
        notes.append("未发现测试文件，已跳过 pytest")

    pyproject = _read_optional(files, "pyproject.toml")
    ruff_configured = any(p.lower() in ("ruff.toml", ".ruff.toml") for p in paths) or "[tool.ruff" in pyproject
    if ruff_configured:
        steps.append(VerifyStep("Lint（ruff）", "python -m ruff check .", required=False, timeout=60))
    else:
        notes.append("未配置 ruff，已跳过 lint")

    mypy_configured = any(p.lower() == "mypy.ini" for p in paths) or "[tool.mypy" in pyproject
    if mypy_configured:
        steps.append(
            VerifyStep(
                "类型检查（mypy）",
                "python -m mypy . --ignore-missing-imports",
                required=False,
                timeout=120,
            )
        )
    else:
        notes.append("未配置 mypy，已跳过类型检查")

    if has_node:
        notes.append("同时检测到 Node 项目；本 profile 只验证 Python 部分")

    return VerifyProfile(stack="python", steps=steps, notes=notes)

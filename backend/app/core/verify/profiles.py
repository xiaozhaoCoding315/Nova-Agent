"""Stack-aware verification profiles.

A profile is a list of deterministic steps.  Each step declares which sandbox
image it runs in, so a repository with a Python backend and a Node frontend can
be verified in one pass without pretending one runtime covers both.
"""
import json
from dataclasses import dataclass, field

from app.core.security.test_guard import is_test_path


@dataclass(frozen=True)
class VerifyStep:
    name: str
    command: str
    required: bool = True
    timeout: int = 90
    image: str = "builder"          # builder | node
    deps_kind: str = "python"       # python | node
    network: bool = False


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


def _read_json(files: dict[str, str], name: str) -> dict:
    raw = _read_optional(files, name)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _node_steps(files: dict[str, str], paths: list[str]) -> tuple[list[VerifyStep], list[str]]:
    package = _read_json(files, "package.json")
    scripts = package.get("scripts") if isinstance(package.get("scripts"), dict) else {}
    dependencies = {
        **(package.get("dependencies") or {}),
        **(package.get("devDependencies") or {}),
    }
    has_pnpm = any(path.lower().endswith("pnpm-lock.yaml") for path in paths)
    has_yarn = any(path.lower().endswith("yarn.lock") for path in paths)
    has_npm_lock = any(path.lower().endswith("package-lock.json") for path in paths)
    has_tsconfig = any(path.lower().endswith("tsconfig.json") for path in paths)
    notes: list[str] = []

    def run_script(name: str) -> str:
        if has_pnpm:
            return f"corepack pnpm run {name}"
        if has_yarn:
            return f"corepack yarn {name}"
        return f"npm run {name}"

    steps: list[VerifyStep] = []
    if dependencies or has_pnpm or has_yarn or has_npm_lock:
        if has_pnpm:
            install = "corepack pnpm install --frozen-lockfile"
        elif has_yarn:
            install = "corepack yarn install --immutable"
        elif has_npm_lock:
            install = "npm ci --no-audit --no-fund"
        else:
            install = "npm install --no-audit --no-fund"
        steps.append(VerifyStep(
            "安装 Node 依赖",
            f"if [ -d node_modules ]; then echo 'node_modules cached'; else {install}; fi",
            required=False,
            timeout=300,
            image="node",
            deps_kind="node",
            network=True,
        ))
    else:
        notes.append("未声明 Node 依赖，已跳过依赖安装")

    if "lint" in scripts:
        steps.append(VerifyStep(
            "Lint（npm）", f"CI=1 {run_script('lint')}", required=False,
            timeout=180, image="node", deps_kind="node",
        ))
    else:
        notes.append("package.json 未配置 lint 脚本")

    if has_tsconfig:
        steps.append(VerifyStep(
            "类型检查（tsc）", "tsc --noEmit", required=True,
            timeout=180, image="node", deps_kind="node",
        ))
    else:
        notes.append("未发现 tsconfig.json，已跳过 TypeScript 类型检查")

    if "test" in scripts:
        steps.append(VerifyStep(
            "Node 测试", f"CI=1 {run_script('test')}", required=True,
            timeout=180, image="node", deps_kind="node",
        ))
    else:
        notes.append("package.json 未配置 test 脚本")

    if "build" in scripts:
        steps.append(VerifyStep(
            "构建（npm）", run_script("build"), required=True,
            timeout=300, image="node", deps_kind="node",
        ))
    else:
        notes.append("package.json 未配置 build 脚本")

    return steps, notes


def detect_profile(files: dict[str, str]) -> VerifyProfile:
    paths = list(files)
    has_node = any(path.lower().endswith("package.json") for path in paths)
    has_python = _has_python(paths)
    if not has_python and not has_node:
        return VerifyProfile(
            stack="unknown",
            unsupported_reason="未检测到可验证的 Python 或 Node 项目",
        )

    steps: list[VerifyStep] = []
    notes: list[str] = []

    if has_python:
        steps.append(VerifyStep("语法检查", "python -m compileall -q .", required=True, timeout=60))
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
            steps.append(VerifyStep(
                "类型检查（mypy）", "python -m mypy . --ignore-missing-imports",
                required=False, timeout=120,
            ))
        else:
            notes.append("未配置 mypy，已跳过类型检查")

    if has_node:
        node_steps, node_notes = _node_steps(files, paths)
        steps.extend(node_steps)
        notes.extend(node_notes)
        if has_python:
            notes.append("同时检测到 Python 与 Node：Python 步骤使用 builder 镜像，Node 步骤使用 node 镜像")

    if not steps:
        return VerifyProfile(
            stack="fullstack" if has_python and has_node else "node" if has_node else "python",
            notes=notes,
            unsupported_reason="项目未配置可验证的脚本",
        )

    stack = "fullstack" if has_python and has_node else "python" if has_python else "node"
    return VerifyProfile(stack=stack, steps=steps, notes=notes)

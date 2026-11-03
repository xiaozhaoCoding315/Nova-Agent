"""Smoke eval tasks: 7 scripted + 3 live."""
from __future__ import annotations

import json

from evals.checks import (
    changed_files_exactly,
    file_contains,
    file_exists,
    file_unchanged,
    final_text_contains,
    llm_saw_compaction,
    llm_saw_image,
    no_error_events,
    no_notice,
    notice_seen,
    plan_has_steps,
    pytest_passes,
    tool_failed_with,
    tool_succeeded,
)
from evals.fixtures import EVAL_PNG_BYTES
from evals.models import EvalTask

_MATHX_INIT = "from .core import add\n"
_MATHX_CORE = "def add(a, b):\n    return a + b\n"
_MATHX_TEST = (
    "from mathx.core import add\n\n\n"
    "def test_add():\n    assert add(2, 3) == 5\n"
)


def _call(call_id: str, name: str, args: dict) -> tuple[dict, ...]:
    return (
        {"type": "tool_calls", "tool_calls": [{
            "id": call_id,
            "name": name,
            "arguments": json.dumps(args, ensure_ascii=False),
        }]},
        {"type": "finish", "finish_reason": "tool_calls"},
    )


def _answer(text: str) -> tuple[dict, ...]:
    return (
        {"type": "content", "content": text},
        {"type": "finish", "finish_reason": "stop"},
    )


def _long_history() -> tuple[dict, ...]:
    messages = []
    for index in range(12):
        role = "user" if index % 2 == 0 else "assistant"
        messages.append({
            "role": role,
            "content": f"第 {index + 1} 段历史。" + "x" * 20_000,
        })
    return tuple(messages)


READ_AND_ANSWER = EvalTask(
    id="read_and_answer",
    mode="scripted",
    category="read",
    description="读取文件并基于内容回答",
    prompt="读取 calc.py，说明 add 函数当前返回什么。",
    fixture="python_small",
    checks=(
        final_text_contains("a - b"),
        tool_succeeded("read_file"),
        no_error_events(),
    ),
    script=(
        _call("call-read", "read_file", {"path": "calc.py"}),
        _answer("add 函数当前返回 a - b。"),
    ),
)

EDIT_FILE_MINIMAL = EvalTask(
    id="edit_file_minimal",
    mode="scripted",
    category="edit",
    description="精确编辑只修改目标文件",
    prompt="calc.py 的 add 函数有缺陷，请精确修改实现，使其返回两数之和。不要动测试文件。",
    fixture="python_small",
    checks=(
        tool_succeeded("edit_file"),
        file_contains("calc.py", "return a + b"),
        file_unchanged("test_calc.py"),
        changed_files_exactly("calc.py"),
    ),
    script=(
        _call("call-read", "read_file", {"path": "calc.py"}),
        _call("call-edit", "edit_file", {
            "path": "calc.py",
            "edits": [{
                "old_string": "return a - b",
                "new_string": "return a + b",
            }],
            "note": "修复 add",
        }),
        _answer("已修复 add，使其返回 a + b。"),
    ),
)

WRITE_FILES_MULTI = EvalTask(
    id="write_files_multi",
    mode="scripted",
    category="edit",
    description="一次写入多个新文件",
    prompt=(
        "创建一个最小 mathx 包：mathx/__init__.py 导出 add，"
        "mathx/core.py 实现 add，tests/test_core.py 写一个通过 pytest 的测试。"
    ),
    fixture="empty",
    checks=(
        tool_succeeded("write_files"),
        file_exists("mathx/__init__.py"),
        file_exists("mathx/core.py"),
        file_exists("tests/test_core.py"),
        file_contains("mathx/__init__.py", "add"),
        file_contains("mathx/core.py", "return a + b"),
        file_contains("tests/test_core.py", "test_add"),
        pytest_passes("tests/test_core.py"),
        changed_files_exactly(
            "mathx/__init__.py", "mathx/core.py", "tests/test_core.py",
        ),
    ),
    script=(
        _call("call-write", "write_files", {"files": {
            "mathx/__init__.py": _MATHX_INIT,
            "mathx/core.py": _MATHX_CORE,
            "tests/test_core.py": _MATHX_TEST,
        }}),
        _answer("已创建 mathx 包和测试。"),
    ),
)

PERMISSION_DENIED = EvalTask(
    id="permission_denied",
    mode="scripted",
    category="policy",
    description="只读模式拒绝写操作且文件不变",
    prompt="把 calc.py 的 add 改成返回 a + b。",
    fixture="python_small",
    permission_mode="readonly",
    checks=(
        tool_failed_with("edit_file", "policy"),
        file_unchanged("calc.py"),
        final_text_contains("只读"),
    ),
    script=(
        _call("call-edit", "edit_file", {
            "path": "calc.py",
            "edits": [{
                "old_string": "return a - b",
                "new_string": "return a + b",
            }],
        }),
        _answer("当前是只读模式，无法修改文件；请切换到可写模式后再试。"),
    ),
)

PLAN_TOOL = EvalTask(
    id="plan_tool",
    mode="scripted",
    category="plan",
    description="update_plan 结构与 plan 事件",
    prompt="先为「修复 add 函数」制定三步计划，不要改代码。",
    fixture="python_small",
    checks=(
        tool_succeeded("update_plan"),
        plan_has_steps(3, in_progress=1),
        file_unchanged("calc.py"),
    ),
    script=(
        _call("call-plan", "update_plan", {
            "steps": [
                {"title": "读取 calc.py", "status": "completed"},
                {"title": "定位缺陷", "status": "in_progress"},
                {"title": "修复并验证", "status": "pending"},
            ],
            "explanation": "先确认实现",
        }),
        _answer("计划已列出，等待确认后再修改。"),
    ),
)

VISION_IMAGE = EvalTask(
    id="vision_image",
    mode="scripted",
    category="vision",
    description="图片以 image_url 进入模型消息",
    prompt="这张图片里是什么？简要回答。",
    fixture="python_small",
    attachments=({
        "id": "eval-file-1",
        "filename": "pixel.png",
        "mime": "image/png",
        "size": len(EVAL_PNG_BYTES),
    },),
    checks=(
        llm_saw_image(),
        no_notice("vision_unsupported"),
        final_text_contains("图片"),
    ),
    script=(
        _answer("图中是一张 1×1 的纯色图片。"),
    ),
)

CONTEXT_COMPACTION = EvalTask(
    id="context_compaction",
    mode="scripted",
    category="context",
    description="超预算历史被压缩并出现 marker",
    prompt="继续。",
    fixture="python_small",
    context_window=8_000,
    history=_long_history(),
    checks=(
        llm_saw_compaction(),
        notice_seen("context_compacted"),
        final_text_contains("历史"),
    ),
    script=(
        _answer("已了解历史。"),
    ),
)

ALL_TASKS = (
    READ_AND_ANSWER,
    EDIT_FILE_MINIMAL,
    WRITE_FILES_MULTI,
    PERMISSION_DENIED,
    PLAN_TOOL,
    VISION_IMAGE,
    CONTEXT_COMPACTION,
)

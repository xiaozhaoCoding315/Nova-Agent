"""Composable checks for eval tasks."""
from __future__ import annotations

import re
import subprocess
from collections.abc import Callable

from evals.models import Check, CheckFailure, EvalRun


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise CheckFailure(message)


def _named(name: str, func: Callable[[EvalRun], None]) -> Check:
    func.__name__ = name
    return func


def final_text_contains(*needles: str) -> Check:
    def check(run: EvalRun) -> None:
        missing = [needle for needle in needles if needle not in run.final_text]
        expect(
            not missing,
            f"最终回答缺少 {missing!r}；实际内容：{run.final_text[:300]!r}",
        )

    return _named(f"final_text_contains{needles!r}", check)


def final_text_matches(pattern: str) -> Check:
    def check(run: EvalRun) -> None:
        expect(
            re.search(pattern, run.final_text) is not None,
            f"最终回答不匹配 {pattern!r}；实际内容：{run.final_text[:300]!r}",
        )

    return _named(f"final_text_matches({pattern!r})", check)


def tool_succeeded(name: str) -> Check:
    def check(run: EvalRun) -> None:
        calls = [call for call in run.tool_calls if call.name == name]
        expect(
            bool(calls),
            f"没有调用工具 {name}；实际调用：{[call.name for call in run.tool_calls]}",
        )
        expect(
            any(call.ok for call in calls),
            f"{name} 未成功：{[(call.error, call.error_class) for call in calls]}",
        )

    return _named(f"tool_succeeded({name})", check)


def tool_failed_with(name: str, error_class: str) -> Check:
    def check(run: EvalRun) -> None:
        calls = [call for call in run.tool_calls if call.name == name]
        expect(bool(calls), f"没有调用工具 {name}")
        expect(
            any(not call.ok and call.error_class == error_class for call in calls),
            f"{name} 没有以 {error_class} 失败："
            f"{[(call.ok, call.error, call.error_class) for call in calls]}",
        )

    return _named(f"tool_failed_with({name},{error_class})", check)


def no_error_events() -> Check:
    def check(run: EvalRun) -> None:
        errors = [event for event in run.events if event.get("event") == "error"]
        expect(
            not errors,
            f"出现 error 事件：{[event.get('data') for event in errors]}",
        )

    return _named("no_error_events", check)


def no_notice(kind: str) -> Check:
    def check(run: EvalRun) -> None:
        matches = [
            event for event in run.events
            if event.get("event") == "notice"
            and (event.get("data") or {}).get("kind") == kind
        ]
        expect(not matches, f"出现 notice kind={kind}：{[e.get('data') for e in matches]}")

    return _named(f"no_notice({kind})", check)


def notice_seen(kind: str) -> Check:
    def check(run: EvalRun) -> None:
        matches = [
            event for event in run.events
            if event.get("event") == "notice"
            and (event.get("data") or {}).get("kind") == kind
        ]
        expect(
            bool(matches),
            f"没有 notice kind={kind}；实际 notices："
            f"{[e.get('data') for e in run.events if e.get('event') == 'notice']}",
        )

    return _named(f"notice_seen({kind})", check)


def file_exists(path: str) -> Check:
    def check(run: EvalRun) -> None:
        expect(run.repo.exists(path), f"文件不存在：{path}")

    return _named(f"file_exists({path})", check)


def file_contains(path: str, needle: str) -> Check:
    def check(run: EvalRun) -> None:
        expect(run.repo.exists(path), f"文件不存在：{path}")
        content = run.repo.read(path)
        expect(
            needle in content,
            f"{path} 未包含 {needle!r}；实际内容前 200 字符：{content[:200]!r}",
        )

    return _named(f"file_contains({path},{needle!r})", check)


def file_unchanged(path: str) -> Check:
    def check(run: EvalRun) -> None:
        expect(run.repo.exists(path), f"文件不存在：{path}")
        expect(
            run.repo.is_unchanged(path),
            f"{path} 被修改；当前内容前 200 字符：{run.repo.read(path)[:200]!r}",
        )

    return _named(f"file_unchanged({path})", check)


def changed_files_exactly(*paths: str) -> Check:
    expected = sorted(path.replace("\\", "/") for path in paths)

    def check(run: EvalRun) -> None:
        actual = run.repo.changed_files()
        missing = [path for path in expected if path not in actual]
        extra = [path for path in actual if path not in expected]
        expect(
            not missing and not extra,
            f"变更文件不符：缺少 {missing}，多出 {extra}；实际 {actual}",
        )

    return _named(f"changed_files_exactly{tuple(expected)!r}", check)


def plan_has_steps(count: int, in_progress: int = 1) -> Check:
    def check(run: EvalRun) -> None:
        plans = [event for event in run.events if event.get("event") == "plan"]
        expect(bool(plans), "没有收到 plan 事件")
        steps = (plans[-1].get("data") or {}).get("steps") or []
        expect(
            len(steps) == count,
            f"计划应有 {count} 步，实际 {len(steps)} 步：{steps}",
        )
        actual = sum(1 for step in steps if step.get("status") == "in_progress")
        expect(
            actual == in_progress,
            f"in_progress 应有 {in_progress} 个，实际 {actual} 个：{steps}",
        )

    return _named(f"plan_has_steps({count},{in_progress})", check)


def llm_saw_image() -> Check:
    def check(run: EvalRun) -> None:
        for messages in run.llm_messages:
            for message in messages:
                content = message.get("content")
                if not isinstance(content, list):
                    continue
                for block in content:
                    if not isinstance(block, dict) or block.get("type") != "image_url":
                        continue
                    url = (block.get("image_url") or {}).get("url") or ""
                    expect(
                        url.startswith("data:image/png;base64,"),
                        f"图片 URL 不是 PNG data URL：{url[:60]!r}",
                    )
                    return
        raise CheckFailure("模型消息中没有 image_url 块")

    return _named("llm_saw_image", check)


def llm_saw_compaction() -> Check:
    def check(run: EvalRun) -> None:
        for messages in run.llm_messages:
            for message in messages:
                content = message.get("content")
                if isinstance(content, str) and "较早内容已压缩" in content:
                    return
        raise CheckFailure("模型消息中没有压缩标记")

    return _named("llm_saw_compaction", check)


def pytest_passes(*targets: str) -> Check:
    def check(run: EvalRun) -> None:
        try:
            result = run.repo.run_pytest(*targets)
        except subprocess.TimeoutExpired as exc:
            raise CheckFailure(f"pytest 超时：{exc}") from exc
        expect(
            result.returncode == 0,
            "pytest 失败："
            f"exit={result.returncode}\n"
            f"stdout:\n{result.stdout[-800:]}\n"
            f"stderr:\n{result.stderr[-800:]}",
        )

    return _named(f"pytest_passes{targets!r}", check)

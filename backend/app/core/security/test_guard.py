"""Reject agent edits that weaken the existing test suite.

The red-green engine requires *new* test files. For in-place editing, this
guard blocks removing test functions or adding skip markers to tests that
already existed before the edit.
"""
import re

_PY_TEST_DEF = re.compile(r"^\s*(?:async\s+)?def\s+(test_[A-Za-z0-9_]+)", re.MULTILINE)
_JS_TEST_DEF = re.compile(
    r"""(?:^|\s)(?:it|test|describe)\s*\(\s*(['"`])([^'"`]+)\1""",
    re.MULTILINE,
)
_SKIP_MARKER = re.compile(
    r"(pytest\.mark\.skip\b|pytest\.skip\(|unittest\.skip|@skip\b"
    r"|(?:it|test|describe)\.skip\b|\bxit\s*\(|\bxdescribe\s*\()"
)


class SuiteIntegrityError(ValueError):
    """The edit removes tests or adds skip markers."""


def is_test_path(path: str) -> bool:
    lowered = str(path or "").lower().replace("\\", "/")
    name = lowered.rsplit("/", 1)[-1]
    return (
        "tests/" in lowered
        or "/test/" in lowered
        or lowered.startswith("test/")
        or name.startswith("test_")
        or "_test." in name
        or ".test." in name
        or ".spec." in name
    )


def _test_names(content: str) -> set[str]:
    python_names = set(_PY_TEST_DEF.findall(content or ""))
    js_names = {match[1] for match in _JS_TEST_DEF.findall(content or "")}
    return python_names | js_names


def assert_tests_preserved(path: str, old_content: str, new_content: str) -> None:
    """Raise when an existing test file loses test cases or gains skips."""
    if not old_content or not is_test_path(path):
        return

    removed = sorted(_test_names(old_content) - _test_names(new_content))
    if removed:
        raise SuiteIntegrityError(
            f"拒绝修改 {path}：删除了已有测试 {', '.join(removed[:5])}。"
            "如确需废弃测试，请人工处理并说明原因。"
        )

    added_skips = sorted(set(_SKIP_MARKER.findall(new_content or "")) - set(_SKIP_MARKER.findall(old_content)))
    if added_skips:
        raise SuiteIntegrityError(
            f"拒绝修改 {path}：新增了跳过标记 {', '.join(added_skips)}。"
            "测试失败应修复实现或测试，不能通过跳过规避。"
        )


def assert_changes_preserve_tests(
    changes: dict[str, str],
    base: dict[str, str | None],
) -> None:
    """Check every changed test file against its pre-edit snapshot."""
    for path, new_content in changes.items():
        old_content = base.get(path)
        if old_content is not None and new_content is not None:
            assert_tests_preserved(path, old_content, new_content)


def assert_new_test_files(
    test_files: dict[str, str],
    base: dict[str, str | None],
) -> None:
    """Red-green tasks must not overwrite existing test files."""
    for path in test_files:
        if is_test_path(path) and base.get(path) is not None:
            raise SuiteIntegrityError(
                f"红-绿任务必须新建测试文件，不能覆盖已有测试：{path}"
            )

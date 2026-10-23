"""Test-integrity guard: no deleting tests or sneaking in skips."""
import pytest

from app.core.security.test_guard import (
    SuiteIntegrityError,
    assert_changes_preserve_tests,
    assert_new_test_files,
    assert_tests_preserved,
    is_test_path,
)


def test_is_test_path():
    assert is_test_path("tests/test_api.py")
    assert is_test_path("src/foo_test.py")
    assert is_test_path("web/app.test.ts")
    assert not is_test_path("app/main.py")


def test_removing_test_is_rejected():
    old = "def test_a():\n    assert 1\n\ndef test_b():\n    assert 2\n"
    new = "def test_a():\n    assert 1\n"
    with pytest.raises(SuiteIntegrityError, match="删除了已有测试"):
        assert_tests_preserved("tests/test_x.py", old, new)


def test_adding_skip_is_rejected():
    old = "def test_a():\n    assert 1\n"
    new = "import pytest\n\n@pytest.mark.skip\ndef test_a():\n    assert 1\n"
    with pytest.raises(SuiteIntegrityError, match="跳过标记"):
        assert_tests_preserved("tests/test_x.py", old, new)


def test_adding_tests_and_non_test_files_are_allowed():
    old = "def test_a():\n    assert 1\n"
    new = old + "\n\ndef test_b():\n    assert 2\n"
    assert_tests_preserved("tests/test_x.py", old, new)
    assert_tests_preserved("app/main.py", "x = 1", "x = 2")


def test_changes_and_new_test_files_guard():
    base = {"tests/test_x.py": "def test_a():\n    assert 1\n"}
    assert_changes_preserve_tests(
        {"tests/test_x.py": "def test_a():\n    assert 2\n"}, base
    )
    with pytest.raises(SuiteIntegrityError, match="必须新建测试文件"):
        assert_new_test_files({"tests/test_x.py": "def test_a():\n    assert 1\n"}, base)

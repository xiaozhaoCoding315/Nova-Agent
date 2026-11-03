"""Fixture repos used by eval tasks."""
from evals.fixtures import create_fixture


def test_python_small_fixture_is_a_git_repo_with_clean_snapshot():
    repo = create_fixture("python_small")
    try:
        assert (repo.root / ".git").is_dir()
        assert repo.changed_files() == []
        assert "return a - b" in repo.read("calc.py")
        assert repo.initial["calc.py"]
    finally:
        repo.cleanup()


def test_changed_files_ignores_caches_and_detects_edits():
    repo = create_fixture("python_small")
    try:
        (repo.root / "calc.py").write_text(
            "def add(a, b):\n    return a + b\n", encoding="utf-8"
        )
        cache = repo.root / "__pycache__"
        cache.mkdir()
        (cache / "calc.cpython-312.pyc").write_bytes(b"x")
        pytest_cache = repo.root / ".pytest_cache"
        pytest_cache.mkdir()
        (pytest_cache / "CACHEDIR.TAG").write_text("x", encoding="utf-8")
        assert repo.changed_files() == ["calc.py"]
    finally:
        repo.cleanup()


def test_changed_files_reports_deleted_file():
    repo = create_fixture("python_small")
    try:
        (repo.root / "README.md").unlink()
        assert repo.changed_files() == ["README.md"]
    finally:
        repo.cleanup()


def test_run_pytest_fails_before_fix_and_passes_after_fix():
    repo = create_fixture("python_small")
    try:
        assert repo.run_pytest().returncode != 0
        (repo.root / "calc.py").write_text(
            "def add(a, b):\n    return a + b\n\n\n"
            "def multiply(a, b):\n    return a * b\n",
            encoding="utf-8",
        )
        assert repo.run_pytest().returncode == 0
    finally:
        repo.cleanup()


def test_is_unchanged_compares_against_initial_snapshot():
    repo = create_fixture("python_small")
    try:
        assert repo.is_unchanged("calc.py")
        (repo.root / "calc.py").write_text("changed", encoding="utf-8")
        assert not repo.is_unchanged("calc.py")
    finally:
        repo.cleanup()

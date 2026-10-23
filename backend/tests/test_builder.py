"""Builder pure-logic tests: file validation and plan sanitizing."""
from app.core.builder.engine import _clean_plan, validate_files


def test_validate_files_accepts_list_and_dict():
    files = validate_files([
        {"path": "app/main.py", "content": "print(1)"},
        {"path": "README.md", "content": "# hi"},
    ])
    assert set(files) == {"app/main.py", "README.md"}

    as_dict = validate_files({"a.py": "x = 1"})
    assert as_dict == {"a.py": "x = 1"}


def test_validate_files_rejects_traversal_and_empty():
    files = validate_files([
        {"path": "../evil.py", "content": "x"},
        {"path": "/abs.py", "content": "x"},
        {"path": "ok.py", "content": "  "},
        {"path": "fine.py", "content": "print(1)"},
    ])
    assert files == {"fine.py": "print(1)"}


def test_validate_files_caps_count_and_size():
    many = [{"path": f"f{i}.py", "content": "x" * 10} for i in range(50)]
    files = validate_files(many)
    assert len(files) <= 30


def test_clean_plan_sanitizes_lists():
    plan = _clean_plan({
        "summary": "todo app",
        "stack": ["Python", "FastAPI"],
        "structure": [{"path": "app/main.py", "purpose": "entry"}],
        "api": [{"method": "GET", "path": "/items", "description": "list"}],
        "milestones": [{"name": "M1"}],
        "risks": ["sqlite locking"],
        "unexpected": "ignored",
    })
    assert plan["summary"] == "todo app"
    assert plan["stack"] == ["Python", "FastAPI"]
    assert plan["structure"][0]["path"] == "app/main.py"
    assert "unexpected" not in plan
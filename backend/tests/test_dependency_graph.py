"""Dependency graph + brain + impact pure-logic tests."""
from app.core.indexing.brain import build_brain
from app.core.indexing.imports import (
    build_path_index,
    extract_imports,
    resolve_import,
)
from app.core.impact.analysis import _dependents, _is_test


# ---------- import extraction ----------

def test_extract_python_imports():
    src = "import os\nfrom app.tax import calculate_tax\nfrom .utils import fmt\nfrom . import helpers\n"
    targets = {i["target"] for i in extract_imports(src, "python")}
    assert "os" in targets
    assert "app.tax" in targets
    assert ".utils" in targets
    assert ".helpers" in targets


def test_extract_python_syntax_error_returns_empty():
    assert extract_imports("def broken(:\n", "python") == []


def test_extract_js_imports():
    src = "import x from './a';\nconst y = require('../lib/b');\nimport('./lazy');\nimport react from 'react';\n"
    targets = [i["target"] for i in extract_imports(src, "typescript")]
    assert "./a" in targets and "../lib/b" in targets and "./lazy" in targets and "react" in targets


def test_extract_java_imports():
    src = "package com.demo;\nimport com.demo.util.Helper;\nimport static org.junit.Assert.assertTrue;\n"
    targets = [i["target"] for i in extract_imports(src, "java")]
    assert "com.demo.util.Helper" in targets
    assert "org.junit.Assert.assertTrue" in targets


# ---------- import resolution ----------

def test_resolve_python_absolute_and_relative():
    paths = ["sample_project/app/tax.py", "sample_project/app/__init__.py",
             "sample_project/app/utils.py", "sample_project/tests/test_tax.py"]
    path_set, suffix = build_path_index(paths)

    assert resolve_import("app.tax", "sample_project/tests/test_tax.py", "from", path_set, suffix) == "sample_project/app/tax.py"
    assert resolve_import(".utils", "sample_project/app/tax.py", "from", path_set, suffix) == "sample_project/app/utils.py"
    assert resolve_import("os", "sample_project/app/tax.py", "import", path_set, suffix) is None


def test_resolve_js_relative_with_extension_index():
    paths = ["web/src/index.ts", "web/src/lib/api.ts", "web/src/components/App.tsx", "web/src/lib/index.ts"]
    path_set, suffix = build_path_index(paths)
    assert resolve_import("./lib/api", "web/src/index.ts", "import", path_set, suffix) == "web/src/lib/api.ts"
    assert resolve_import("./components/App", "web/src/index.ts", "import", path_set, suffix) == "web/src/components/App.tsx"
    assert resolve_import("../lib", "web/src/components/App.tsx", "import", path_set, suffix) == "web/src/lib/index.ts"
    assert resolve_import("react", "web/src/index.ts", "import", path_set, suffix) is None


def test_resolve_java_by_suffix():
    paths = ["server/src/main/java/com/demo/UserService.java", "server/src/main/java/com/demo/Main.java"]
    path_set, suffix = build_path_index(paths)
    assert resolve_import(
        "com.demo.UserService", "server/src/main/java/com/demo/Main.java", "import", path_set, suffix
    ).endswith("UserService.java")


# ---------- brain ----------

def test_build_brain_core_sections():
    files = [
        {"path": "app/main.py", "language": "python", "line_count": 40, "is_doc": False},
        {"path": "app/tax.py", "language": "python", "line_count": 30, "is_doc": False},
        {"path": "tests/test_tax.py", "language": "python", "line_count": 12, "is_doc": False},
        {"path": "README.md", "language": "markdown", "line_count": 8, "is_doc": True},
    ]
    symbols = [
        {"name": "main", "kind": "function", "path": "app/main.py", "line_start": 1, "signature": "def main()"},
        {"name": "calculate_tax", "kind": "function", "path": "app/tax.py", "line_start": 6, "signature": "def calculate_tax(...)"},
    ]
    deps = [
        {"source_path": "app/main.py", "resolved_path": "app/tax.py"},
        {"source_path": "tests/test_tax.py", "resolved_path": "app/tax.py"},
    ]
    brain = build_brain(files, symbols, deps, {"python": 3, "markdown": 1})

    assert brain["totals"]["files"] == 4
    assert brain["totals"]["tests"] == 1
    assert "app/main.py" in brain["entry_points"]
    assert brain["hot_files"][0]["path"] == "app/tax.py"  # most depended-on
    assert ["app/main.py", "app/tax.py"] in brain["graph"]["edges"]
    assert any(g["name"] == "calculate_tax" for g in brain["glossary"])
    assert brain["reading_order"][0] in ("app/main.py", "README.md")


# ---------- impact helpers ----------

def test_dependents_direct_and_transitive():
    deps = [
        {"source_path": "a.py", "resolved_path": "core.py"},
        {"source_path": "b.py", "resolved_path": "a.py"},
        {"source_path": "c.py", "resolved_path": "b.py"},
    ]
    direct, transitive, levels = _dependents({"core.py"}, deps, depth=2)
    assert direct == ["a.py"]
    assert transitive == ["b.py"]
    assert levels["a.py"] == 1 and levels["b.py"] == 2


def test_is_test_detection():
    assert _is_test("tests/test_x.py")
    assert _is_test("src/foo.spec.ts")
    assert not _is_test("src/foo.py")
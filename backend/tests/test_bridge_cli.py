"""Nova bridge CLI: pure helper functions (zip packing + manifest)."""
import importlib.util
import sys

import pytest


@pytest.fixture(scope="module")
def nova_cli():
    spec = importlib.util.spec_from_file_location("nova_cli", "nova.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["nova_cli"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_zip_dir_ignores_junk(tmp_path, nova_cli):
    import zipfile
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text("print(1)", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "x.js").write_text("junk", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("x", encoding="utf-8")
    out = tmp_path.parent / "bridge-test.zip"
    count = nova_cli._zip_dir(tmp_path, out)
    assert count == 1
    with zipfile.ZipFile(out) as zf:
        assert zf.namelist() == ["app/main.py"]
    out.unlink(missing_ok=True)


def test_manifest_stable_and_filtered(tmp_path, nova_cli):
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("x", encoding="utf-8")
    m = nova_cli._manifest(tmp_path)
    assert m == {"a.txt": "5d41402abc4b2a76b9719d911017c592"}
    (tmp_path / "a.txt").write_text("world", encoding="utf-8")
    assert nova_cli._manifest(tmp_path)["a.txt"] != m["a.txt"]

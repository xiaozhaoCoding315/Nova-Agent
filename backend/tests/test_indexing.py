"""Indexing unit tests: chunker line numbers, symbol extraction, zip safety."""
import zipfile
from pathlib import Path

import pytest

from app.core.indexing.chunker import chunk_code, chunk_doc, chunk_file
from app.core.indexing.languages import detect_language, is_supported
from app.core.indexing.symbols import extract_symbols
from app.core.indexing.walker import iter_source_files, safe_extract_zip, strip_root_dir

PY_SRC = '''import os


def alpha(x):
    return x + 1


def beta():
    return 2


class Gamma:
    def method(self):
        return 3
'''

TS_SRC = '''export class UserService {
  private db: any;

  async findUser(id: string) {
    return this.db.query(id);
  }
}

export function main() {
  return 1;
}
'''


# ---------- chunker ----------

def test_code_chunks_cover_symbols_with_accurate_lines():
    chunks = chunk_code(PY_SRC, "python")
    assert chunks and all(c["kind"] == "code" for c in chunks)

    lines = PY_SRC.splitlines()
    for sym in extract_symbols(PY_SRC, "python"):
        containing = [
            c for c in chunks
            if c["line_start"] <= sym["line_start"] and sym["line_end"] <= c["line_end"]
        ]
        assert containing, f"symbol {sym['name']} not covered by any chunk"
        text = "\n".join(lines[containing[0]["line_start"] - 1:containing[0]["line_end"]])
        assert sym["name"] in text  # line numbers really point at the code


def test_oversized_block_is_split_within_budget():
    big_fn = "def huge():\n" + "\n".join(f"    x{i} = {i}" for i in range(400))
    chunks = chunk_code(big_fn, "python")
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk["content"]) <= 1400


def test_doc_chunks_split_at_headings():
    md = "# Title\nalpha\n\n## Section A\ncontent a\n\n## Section B\ncontent b\n"
    chunks = chunk_doc(md, "markdown")
    assert len(chunks) >= 2
    assert chunks[0]["line_start"] == 1
    section_b = next(c for c in chunks if "content b" in c["content"])
    assert md.splitlines()[section_b["line_start"] - 1].startswith("## Section B")


def test_chunk_file_dispatches_code_and_doc():
    assert chunk_file(PY_SRC, "python", False)[0]["kind"] == "code"
    assert chunk_file("# t\nbody", "markdown", True)[0]["kind"] == "doc"


def test_ts_code_chunks_extract_class():
    chunks = chunk_code(TS_SRC, "typescript")
    assert any("class UserService" in c["content"] for c in chunks)


# ---------- symbols ----------

def test_python_symbols_kinds_and_parents():
    symbols = extract_symbols(PY_SRC, "python")
    by_name = {s["name"]: s for s in symbols}
    assert by_name["alpha"]["kind"] == "function"
    assert by_name["Gamma"]["kind"] == "class"
    assert by_name["method"]["kind"] == "method"
    assert by_name["method"]["parent"] == "Gamma"


def test_ts_symbols_brace_ranges():
    symbols = extract_symbols(TS_SRC, "typescript")
    names = {s["name"]: s for s in symbols}
    assert "UserService" in names and "main" in names
    assert names["UserService"]["line_end"] > names["UserService"]["line_start"]


def test_go_and_java_symbols():
    go = "package main\n\ntype Server struct {\n\tport int\n}\n\nfunc (s *Server) Start() {\n}\n\nfunc main() {\n}\n"
    go_names = {s["name"] for s in extract_symbols(go, "go")}
    assert {"Server", "Start", "main"} <= go_names

    java = "public class Demo {\n    public int add(int a, int b) {\n        return a + b;\n    }\n}\n"
    java_syms = {s["name"]: s for s in extract_symbols(java, "java")}
    assert "Demo" in java_syms and "add" in java_syms


def test_python_syntax_error_returns_empty_not_raise():
    assert extract_symbols("def broken(:\n  pass", "python") == []


# ---------- languages ----------

def test_detect_language():
    assert detect_language("a/b.py") == ("python", False)
    assert detect_language("README.md") == ("markdown", True)
    assert detect_language("photo.png") == ("", False)
    assert is_supported("x.java") and not is_supported("x.exe")


# ---------- walker ----------

def test_safe_extract_zip_rejects_traversal(tmp_path):
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("../evil.txt", "x")
    with pytest.raises(ValueError):
        safe_extract_zip(str(evil), str(tmp_path / "out"), 100, 10_000)


def test_safe_extract_zip_extracts_and_skips_oversized(tmp_path):
    z = tmp_path / "ok.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("pkg/main.py", "print(1)")
        zf.writestr("pkg/huge.py", "x" * 5000)
    out = tmp_path / "out"
    count = safe_extract_zip(str(z), str(out), 100, 1000)
    assert count == 1
    assert (out / "pkg" / "main.py").exists()
    assert not (out / "pkg" / "huge.py").exists()


def test_safe_extract_zip_rejects_empty_zip(tmp_path):
    z = tmp_path / "empty.zip"
    with zipfile.ZipFile(z, "w"):
        pass
    with pytest.raises(ValueError):
        safe_extract_zip(str(z), str(tmp_path / "out"), 100, 10_000)


def test_strip_root_dir_hoists_single_dir(tmp_path):
    single = tmp_path / "a"
    (single / "repo-main").mkdir(parents=True)
    (single / "repo-main" / "x.py").write_text("pass")
    assert strip_root_dir(str(single)) == str(single / "repo-main")

    multi = tmp_path / "b"
    (multi / "src").mkdir(parents=True)
    (multi / "README.md").write_text("hi")
    assert strip_root_dir(str(multi)) == str(multi)


def test_iter_source_files_skips_noise_and_binaries(tmp_path):
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "lib.js").write_text("x")
    (tmp_path / "main.py").write_text("print(1)")
    (tmp_path / "README.md").write_text("# hi")
    (tmp_path / "img.png").write_bytes(b"\x00\x01binary")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref")

    found = {rel for rel, _, _ in iter_source_files(str(tmp_path), 10_000)}
    assert found == {"main.py", "README.md"}
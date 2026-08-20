"""Unit tests for language-aware code chunking."""
from app.utils.text_splitter import (
    detect_language, chunk_code, chunk_document, chunk_text,
)

_PY_SAMPLE = (
    "import os\n"
    "\n"
    "def alpha(x):\n"
    "    return x + 1\n"
    "\n"
    "class Beta:\n"
    "    def method(self):\n"
    "        return 'beta'\n"
    "\n"
    "def gamma(y):\n"
    "    total = 0\n"
    "    for i in range(y):\n"
    "        total += i\n"
    "    return total\n"
)

_LONG_FUNC = "def big(n):\n" + "".join(f"    v{i} = {i}\n" for i in range(150)) + "    return n\n"


def test_detect_language():
    assert detect_language("main.py") == "python"
    assert detect_language("App.java") == "java"
    assert detect_language("index.tsx") == "typescript"
    assert detect_language("service.go") == "go"
    assert detect_language("notes.md") is None
    assert detect_language("data.json") == "json"


def test_python_chunks_split_at_declarations():
    chunks = chunk_code(_PY_SAMPLE, "sample.py", "python")
    contents = [c.content for c in chunks]
    # each top-level def/class lands in its own chunk
    assert any(c.startswith("def alpha") for c in contents)
    assert any(c.startswith("class Beta") for c in contents)
    assert any(c.startswith("def gamma") for c in contents)
    # class body stays together with its declaration
    beta = next(c for c in contents if c.startswith("class Beta"))
    assert "method" in beta
    # language tag recorded
    assert all(c.metadata.get("language") == "python" for c in chunks)
    # chunk_index is sequential
    assert [c.metadata["chunk_index"] for c in chunks] == list(range(len(chunks)))


def test_oversized_function_falls_back_to_line_window():
    chunks = chunk_code(_LONG_FUNC, "big.py", "python")
    assert len(chunks) >= 2
    assert all(len(c.content) <= 2000 for c in chunks)
    assert chunks[0].content.startswith("def big")


def test_chunk_document_dispatches_by_extension():
    code_chunks = chunk_document(_PY_SAMPLE, "sample.py")
    assert code_chunks and code_chunks[0].metadata.get("language") == "python"

    md = "# Title\n\n" + "正文内容。\n\n" * 60
    md_chunks = chunk_document(md, "doc.md")
    assert all("language" not in c.metadata for c in md_chunks)
    assert md_chunks  # prose chunker still works


def test_prose_chunker_unchanged():
    text = "# A\n\npara\n\n# B\n\npara2"
    chunks = chunk_text(text, source="t.md")
    assert len(chunks) == 2

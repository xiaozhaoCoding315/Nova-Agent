"""L3 full-text evidence tests with a minimal, hand-built PDF."""
from __future__ import annotations

from pathlib import Path

from app.core.thesis.citations.fulltext import (
    extract_pdf_pages,
    locate_reference,
    locate_references,
)

RAW = (
    "[1] He K, Zhang X, Ren S, et al. Deep residual learning for image "
    "recognition[C]. Proceedings of the IEEE conference on computer vision "
    "and pattern recognition, 2016: 770-778."
)


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _make_pdf(path: Path, pages: list[list[str]]) -> None:
    font_id = 3 + 2 * len(pages)
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
    ]
    page_ids = [3 + index for index in range(len(pages))]
    content_ids = [3 + len(pages) + index for index in range(len(pages))]
    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode())
    for content_id in content_ids:
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Contents {content_id} 0 R "
                f"/Resources << /Font << /F1 {font_id} 0 R >> >> >>"
            ).encode()
        )
    for lines in pages:
        operations = ["BT /F1 12 Tf 72 720 Td"]
        for line in lines:
            operations.append(f"({_escape(line)}) Tj 0 -16 Td")
        operations.append("ET")
        stream = "\n".join(operations).encode("latin-1", "replace")
        objects.append(
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n"
            + stream + b"\nendstream"
        )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    output = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for index, body in enumerate(objects, start=1):
        offsets.append(len(output))
        output += f"{index} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_position = len(output)
    output += f"xref\n0 {len(objects) + 1}\n".encode()
    output += b"0000000000 65535 f \n"
    for offset in offsets:
        output += f"{offset:010d} 00000 n \n".encode()
    output += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_position}\n%%EOF\n"
    ).encode()
    path.write_bytes(bytes(output))


def test_extract_pdf_pages_reads_page_text(tmp_path):
    path = tmp_path / "ref.pdf"
    _make_pdf(path, [["Cover page"], ["Deep residual learning for image recognition"]])
    pages = extract_pdf_pages(path)
    assert len(pages) == 2
    assert "Deep residual" in pages[1]


def test_locate_reference_by_title(tmp_path):
    path = tmp_path / "ref.pdf"
    _make_pdf(
        path,
        [
            ["Some other paper about databases"],
            ["Deep residual learning for image recognition"],
        ],
    )
    pages = extract_pdf_pages(path)
    match = locate_reference(RAW, pages)
    assert match is not None
    assert match["page"] == 2
    assert match["method"] == "title"
    assert match["score"] >= 0.9
    assert "Deep residual" in match["quote"]


def test_locate_reference_by_doi(tmp_path):
    path = tmp_path / "ref.pdf"
    _make_pdf(path, [["DOI 10.1109/CVPR.2016.90 is printed in this paper."]])
    pages = extract_pdf_pages(path)
    match = locate_reference(
        RAW, pages, doi="10.1109/CVPR.2016.90"
    )
    assert match is not None
    assert match["method"] == "doi"
    assert match["score"] == 1.0


def test_locate_reference_returns_none_when_absent(tmp_path):
    path = tmp_path / "ref.pdf"
    _make_pdf(path, [["Totally unrelated content about marine biology."]])
    pages = extract_pdf_pages(path)
    assert locate_reference(RAW, pages) is None


def test_locate_references_picks_best_pdf(tmp_path):
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    _make_pdf(first, [["Unrelated"]])
    _make_pdf(second, [["Deep residual learning for image recognition"]])
    pdfs = [
        {"id": "pdf-1", "filename": "first.pdf", "pages": extract_pdf_pages(first)},
        {"id": "pdf-2", "filename": "second.pdf", "pages": extract_pdf_pages(second)},
    ]
    matches = locate_references(
        [{"index": 1, "raw": RAW, "doi": "10.1109/CVPR.2016.90"}], pdfs
    )
    assert len(matches) == 1
    assert matches[0]["pdf_id"] == "pdf-2"
    assert matches[0]["page"] == 1

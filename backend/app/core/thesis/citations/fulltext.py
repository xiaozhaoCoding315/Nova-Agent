"""L3 citation evidence: locate candidate quotes in user-supplied PDFs.

This layer is deterministic: it finds the page and text that *may* support a
reference.  It does not decide whether the citation is appropriate.  Every
candidate stays ``needs_review`` until the user confirms it.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from app.core.thesis.citations.metadata import (
    extract_doi,
    guess_reference_title,
    normalize_text,
)

MAX_PAGES = 500
MAX_QUOTE = 420
STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "are", "was", "were",
    "have", "has", "had", "not", "but", "into", "than", "then", "their", "its",
    "can", "may", "our", "you", "all", "any", "how", "why", "what", "when",
}


def extract_pdf_pages(path: Path) -> list[str]:
    """Extract text per page.  Raise a readable error for scans/encrypted files."""
    reader = PdfReader(str(path))
    if reader.is_encrypted:
        try:
            if not reader.decrypt(""):
                raise ValueError("PDF 已加密，无法读取")
        except ValueError:
            raise
        except Exception as exc:  # noqa: BLE001 - pypdf raises various errors
            raise ValueError("PDF 已加密，无法读取") from exc
    total_pages = len(reader.pages)
    if total_pages > MAX_PAGES:
        raise ValueError(f"PDF 共 {total_pages} 页，超过 {MAX_PAGES} 页上限")
    pages: list[str] = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001 - a broken page should not kill the batch
            pages.append("")
    if not any(text.strip() for text in pages):
        raise ValueError("PDF 没有可提取的文字（可能是扫描件），请使用带文字层的 PDF")
    return pages


def _segments(page_text: str) -> list[str]:
    return [
        segment.strip()
        for segment in re.split(r"\n+|(?<=[。！？.!?])\s+", page_text)
        if segment.strip()
    ]


def _tokens(text: str) -> list[str]:
    latin = re.findall(r"[a-z][a-z\-]{3,}", text.lower())
    tokens = [word for word in latin if word not in STOPWORDS]
    for chunk in re.findall(r"[㐀-鿿]+", text):
        if len(chunk) <= 2:
            tokens.append(chunk)
        else:
            tokens.extend(chunk[i : i + 2] for i in range(len(chunk) - 1))
    return tokens


def _prepare_pages(pages: list[str]) -> list[list[tuple[str, str, set[str]]]]:
    """Normalize each candidate segment once, then reuse it for every entry."""
    prepared: list[list[tuple[str, str, set[str]]]] = []
    for page_text in pages:
        segments: list[tuple[str, str, set[str]]] = []
        for segment in _segments(page_text):
            segment_norm = normalize_text(segment)
            if segment_norm:
                segments.append((segment, segment_norm, set(_tokens(segment))))
        prepared.append(segments)
    return prepared


def _snippet(segment: str, title: str, doi: str) -> str:
    text = re.sub(r"\s+", " ", segment).strip()
    if len(text) <= MAX_QUOTE:
        return text
    needle = doi or title
    position = text.lower().find(needle.lower()) if needle else -1
    if position < 0:
        return text[:MAX_QUOTE] + "…"
    start = max(0, position - 120)
    end = min(len(text), position + len(needle) + 160)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return (prefix + text[start:end] + suffix)[: MAX_QUOTE + 20]


def _locate_prepared(
    reference_raw: str,
    prepared_pages: list[list[tuple[str, str, set[str]]]],
    *,
    doi: str | None = None,
) -> dict[str, Any] | None:
    title = guess_reference_title(reference_raw)
    title_norm = normalize_text(title)
    title_tokens = set(_tokens(title))
    target_doi = (doi or extract_doi(reference_raw) or "").lower()
    best: tuple[float, str, int, str] | None = None

    for page_number, segments in enumerate(prepared_pages, start=1):
        for segment, segment_norm, segment_tokens in segments:
            if target_doi and target_doi in segment.lower():
                candidate = (1.0, "doi", page_number, segment)
            elif title_norm and len(title_norm) >= 4 and title_norm in segment_norm:
                candidate = (0.97, "title", page_number, segment)
            elif len(title_tokens) >= 3:
                score = len(title_tokens & segment_tokens) / len(title_tokens)
                if score < 0.6:
                    continue
                candidate = (score * 0.9, "tokens", page_number, segment)
            else:
                continue
            if best is None or candidate[0] > best[0]:
                best = candidate

    if best is None:
        return None
    score, method, page_number, segment = best
    return {
        "page": page_number,
        "quote": _snippet(segment, title, target_doi),
        "score": round(score, 3),
        "method": method,
    }


def locate_reference(
    reference_raw: str,
    pages: list[str],
    *,
    doi: str | None = None,
) -> dict[str, Any] | None:
    """Return the best candidate ``{page, quote, score, method}`` for one entry."""
    return _locate_prepared(reference_raw, _prepare_pages(pages), doi=doi)


def locate_references(
    references: list[dict[str, Any]],
    pdfs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Match every reference against every PDF and keep the best candidate."""
    prepared_pdfs = [
        {
            **pdf,
            "_prepared": _prepare_pages(list(pdf.get("pages") or [])),
        }
        for pdf in pdfs
    ]
    matches: list[dict[str, Any]] = []
    for reference in references:
        raw = str(reference.get("raw") or "")
        best: dict[str, Any] | None = None
        for pdf in prepared_pdfs:
            candidate = _locate_prepared(
                raw,
                pdf["_prepared"],
                doi=reference.get("doi"),
            )
            if candidate is None:
                continue
            if best is None or candidate["score"] > best["score"]:
                best = {
                    **candidate,
                    "pdf_id": pdf.get("id"),
                    "pdf_filename": pdf.get("filename") or "",
                }
        if best is not None:
            matches.append(
                {
                    "reference_index": reference.get("index"),
                    "reference_raw": raw,
                    **best,
                }
            )
    return matches


__all__ = [
    "extract_pdf_pages",
    "locate_reference",
    "locate_references",
]

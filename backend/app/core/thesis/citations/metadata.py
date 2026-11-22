"""L2 citation metadata verification via Crossref (DOI only).

Only DOIs are sent to Crossref.  The reference text and the thesis itself never
leave the machine.  A "not found" result is **not** evidence that a reference
is fake; every status is phrased so the user has to confirm the final call.
"""
from __future__ import annotations

import asyncio
import difflib
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

import httpx

CROSSREF_API = "https://api.crossref.org/works/{doi}"
USER_AGENT = (
    "Nova-Agent/2.2.2 (thesis-mode; "
    "+https://github.com/xiaozhaoCoding315/Nova-Agent)"
)
CACHE_TTL = timedelta(days=30)
DOI_RE = re.compile(r"\b10\.\d{4,9}/[^\s\"<>]+", re.IGNORECASE)
CJK_RE = re.compile(r"[㐀-鿿]")
TYPE_MARKER_RE = re.compile(
    r"\[(?:J|M|C|D|N|R|S|P|A|G|Z|EB/OL|DB/OL|J/OL|M/OL|C/OL)\]"
)
ENTRY_NUMBER_RE = re.compile(r"^\s*[\[［]\d+[\]］]\s*")
YEAR_RE = re.compile(r"(?:19|20)\d{2}")

METADATA_STATUSES = (
    "verified",
    "partial",
    "mismatch",
    "not_found",
    "needs_review",
    "no_doi",
)


def extract_doi(raw: str | None) -> str | None:
    """Return the first DOI in a reference entry, without trailing punctuation."""
    if not raw:
        return None
    match = DOI_RE.search(raw)
    if not match:
        return None
    doi = match.group(0).rstrip(".,;:)]}，。；：）】")
    return doi.lower() or None


def guess_reference_title(raw: str) -> str:
    """Best-effort title extraction for GB/T 7714-style entries.

    This is only used to *locate* candidate text; it never decides that a
    reference is wrong.  When no ``[J]/[M]/...`` marker exists, the longest
    middle segment is used.
    """
    text = ENTRY_NUMBER_RE.sub("", raw or "").strip()
    if not text:
        return ""
    parts = [part.strip() for part in re.split(r"[.．。]\s*", text) if part.strip()]
    for part in parts:
        if TYPE_MARKER_RE.search(part):
            title = TYPE_MARKER_RE.sub("", part).strip()
            if title:
                return title
    if len(parts) >= 3:
        return max(parts[1:-1], key=len).strip()
    if len(parts) == 2:
        return parts[1].strip()
    return text


def normalize_text(text: str) -> str:
    """Lowercase, NFKC, and drop punctuation/whitespace for containment checks."""
    normalized = unicodedata.normalize("NFKC", text or "").lower()
    return re.sub(r"[\W_]+", "", normalized, flags=re.UNICODE)


def _year(text: str) -> str:
    match = YEAR_RE.search(text or "")
    return match.group(0) if match else ""


def title_similarity(title: str, raw: str) -> float:
    """Share of the title that appears, in order, inside the raw entry."""
    clean_title = normalize_text(title)
    clean_raw = normalize_text(raw)
    if not clean_title or not clean_raw:
        return 0.0
    if clean_title in clean_raw:
        return 1.0
    matcher = difflib.SequenceMatcher(None, clean_title, clean_raw, autojunk=False)
    return matcher.find_longest_match(0, len(clean_title), 0, len(clean_raw)).size / len(
        clean_title
    )


def classify_reference(
    raw: str,
    metadata: dict[str, Any] | None,
    *,
    error: str = "",
) -> dict[str, Any]:
    """Compare one local entry with resolved Crossref metadata.

    Statuses are conservative: anything that cannot be checked stays
    ``partial``/``needs_review`` rather than being called verified.
    """
    doi = extract_doi(raw)
    if error:
        return {
            "status": "needs_review",
            "detail": error,
            "doi": doi,
            "metadata": metadata or {},
        }
    if not metadata:
        return {
            "status": "not_found",
            "detail": "Crossref 未找到该 DOI；未找到不代表文献不存在，请人工确认。",
            "doi": doi,
            "metadata": {},
        }

    title = str(metadata.get("title") or "")
    ref_year = _year(raw)
    meta_year = str(metadata.get("year") or "")
    reasons: list[str] = []

    if not title:
        title_state = "unknown"
        reasons.append("Crossref 返回的元数据没有题名")
    elif CJK_RE.search(raw) and not CJK_RE.search(title):
        title_state = "unverified"
        reasons.append("DOI 已解析；中文题名未做逐字比对")
    else:
        ratio = title_similarity(title, raw)
        if ratio >= 0.9:
            title_state = "match"
        elif ratio >= 0.55:
            title_state = "partial"
            reasons.append(f"题名相似度约 {ratio:.0%}")
        else:
            title_state = "mismatch"
            reasons.append("Crossref 题名与本地条目差异较大")

    year_state = "unknown"
    if ref_year and meta_year:
        if ref_year == meta_year:
            year_state = "match"
        else:
            year_state = "mismatch"
            reasons.append(f"年份不一致：条目 {ref_year} / Crossref {meta_year}")

    author_state = "unknown"
    authors = [str(name) for name in (metadata.get("authors") or []) if name]
    if authors and not CJK_RE.search(raw):
        family = authors[0].split()[-1].lower()
        if family and family in raw.lower():
            author_state = "match"
        else:
            author_state = "mismatch"
            reasons.append("Crossref 作者与本地条目未对应")

    if title_state == "mismatch" or year_state == "mismatch":
        status = "mismatch"
    elif (
        title_state == "match"
        and year_state in ("match", "unknown")
        and author_state != "mismatch"
    ):
        status = "verified"
        if year_state == "match":
            reasons.append(
                "DOI、题名、作者与年份一致"
                if author_state == "match"
                else "DOI、题名与年份一致"
            )
        else:
            reasons.append("DOI 与题名一致；年份未比对")
    else:
        status = "partial"

    return {"status": status, "detail": "；".join(reasons), "doi": doi, "metadata": metadata}


def cache_is_fresh(
    fetched_at: datetime | None,
    *,
    now: datetime | None = None,
    ttl: timedelta = CACHE_TTL,
) -> bool:
    if fetched_at is None:
        return False
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=timezone.utc)
    return (now or datetime.now(timezone.utc)) - fetched_at < ttl


def _map_crossref(doi: str, message: dict[str, Any]) -> dict[str, Any]:
    authors: list[str] = []
    for author in message.get("author") or []:
        if not isinstance(author, dict):
            continue
        name = " ".join(
            part for part in (author.get("given"), author.get("family")) if part
        ).strip() or str(author.get("name") or "")
        if name:
            authors.append(name)
    issued = (
        message.get("issued")
        or message.get("published-print")
        or message.get("published-online")
        or {}
    )
    date_parts = (issued.get("date-parts") or [[None]])[0]
    year = date_parts[0] if date_parts else None
    return {
        "doi": doi,
        "title": " ".join(message.get("title") or []).strip(),
        "authors": authors[:10],
        "year": year,
        "container": " ".join(message.get("container-title") or []).strip(),
        "volume": str(message.get("volume") or ""),
        "issue": str(message.get("issue") or ""),
        "pages": str(message.get("page") or ""),
        "type": str(message.get("type") or ""),
        "url": str(message.get("URL") or f"https://doi.org/{doi}"),
    }


async def fetch_doi(doi: str, *, client: httpx.AsyncClient | None = None) -> dict[str, Any]:
    """Resolve one DOI.  Network/protocol failures become ``needs_review``."""
    owns_client = client is None
    http = client or httpx.AsyncClient(
        timeout=8.0,
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
    )
    try:
        response = await http.get(
            CROSSREF_API.format(doi=quote(doi, safe="/")),
            headers={"User-Agent": USER_AGENT},
        )
    except httpx.HTTPError as exc:
        return {
            "ok": False,
            "status": "needs_review",
            "error": f"联网失败（{type(exc).__name__}），请稍后重试",
        }
    finally:
        if owns_client:
            await http.aclose()

    if response.status_code == 404:
        return {"ok": False, "status": "not_found", "error": "Crossref 未找到该 DOI"}
    if response.status_code >= 400:
        return {
            "ok": False,
            "status": "needs_review",
            "error": f"Crossref 返回 HTTP {response.status_code}",
        }
    try:
        payload = response.json()
    except ValueError:
        return {"ok": False, "status": "needs_review", "error": "Crossref 返回了非 JSON 内容"}
    message = payload.get("message") if isinstance(payload, dict) else None
    if not isinstance(message, dict):
        return {"ok": False, "status": "needs_review", "error": "Crossref 响应缺少 message"}
    return {"ok": True, "status": "verified", "metadata": _map_crossref(doi, message)}


async def fetch_dois(
    dois: list[str],
    *,
    client: httpx.AsyncClient | None = None,
    concurrency: int = 3,
) -> dict[str, dict[str, Any]]:
    """Resolve a batch of DOIs with at most ``concurrency`` requests in flight."""
    unique = list(dict.fromkeys(doi.lower() for doi in dois if doi))
    if not unique:
        return {}
    owns_client = client is None
    http = client or httpx.AsyncClient(
        timeout=8.0,
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
    )
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def one(doi: str) -> dict[str, Any]:
        async with semaphore:
            return await fetch_doi(doi, client=http)

    try:
        results = await asyncio.gather(*(one(doi) for doi in unique))
    finally:
        if owns_client:
            await http.aclose()
    return dict(zip(unique, results))

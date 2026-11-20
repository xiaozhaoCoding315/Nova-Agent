"""L2 DOI metadata tests: extraction, classification and Crossref mapping."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.core.thesis import service
from app.core.thesis.citations.metadata import (
    cache_is_fresh,
    classify_reference,
    extract_doi,
    fetch_doi,
    fetch_dois,
    guess_reference_title,
    title_similarity,
)

RAW_EN = (
    "[1] He K, Zhang X, Ren S, et al. Deep residual learning for image "
    "recognition[C]. Proceedings of the IEEE conference on computer vision "
    "and pattern recognition, 2016: 770-778. DOI: 10.1109/CVPR.2016.90."
)
RAW_CJK = (
    "[2] 张三. 深度学习在图像识别中的应用研究[J]. 计算机学报, 2020, 43(1): 1-10. "
    "DOI: 10.1234/cjk.2020.001."
)
CROSSREF = {
    "status": "ok",
    "message": {
        "title": ["Deep residual learning for image recognition"],
        "author": [
            {"given": "Kaiming", "family": "He"},
            {"given": "Xiangyu", "family": "Zhang"},
        ],
        "issued": {"date-parts": [[2016]]},
        "container-title": [
            "Proceedings of the IEEE conference on computer vision and pattern recognition"
        ],
        "volume": "",
        "issue": "",
        "page": "770-778",
        "type": "proceedings-article",
        "URL": "https://doi.org/10.1109/CVPR.2016.90",
    },
}


def test_extract_doi_strips_trailing_punctuation():
    assert extract_doi(RAW_EN) == "10.1109/cvpr.2016.90"
    assert extract_doi("没有 DOI 的条目") is None
    assert extract_doi("DOI: (10.1000/xyz-1).") == "10.1000/xyz-1"


def test_guess_reference_title_uses_type_marker():
    assert guess_reference_title(RAW_EN) == "Deep residual learning for image recognition"
    assert guess_reference_title(RAW_CJK) == "深度学习在图像识别中的应用研究"
    assert guess_reference_title("[3] 李四. 一个没有类型标记的题名. 某期刊, 2021.")


def test_title_similarity_is_containment_based():
    assert title_similarity("Deep residual learning for image recognition", RAW_EN) == 1.0
    assert title_similarity("A completely unrelated paper about databases", RAW_EN) < 0.5


def test_classify_verified_when_doi_title_and_year_match():
    result = classify_reference(RAW_EN, {
        "title": "Deep residual learning for image recognition",
        "year": 2016,
    })
    assert result["status"] == "verified"


def test_classify_mismatch_when_year_differs():
    result = classify_reference(RAW_EN, {
        "title": "Deep residual learning for image recognition",
        "year": 2015,
    })
    assert result["status"] == "mismatch"
    assert "年份" in result["detail"]


def test_classify_partial_for_cjk_title_not_compared():
    result = classify_reference(RAW_CJK, {
        "title": "Deep learning for image recognition",
        "year": 2020,
    })
    assert result["status"] == "partial"
    assert "中文题名" in result["detail"]


def test_classify_not_found_never_calls_reference_fake():
    result = classify_reference(RAW_EN, None)
    assert result["status"] == "not_found"
    assert "不代表文献不存在" in result["detail"]


def test_classify_network_error_stays_needs_review():
    result = classify_reference(RAW_EN, None, error="联网失败")
    assert result["status"] == "needs_review"


def test_cache_freshness():
    now = datetime.now(timezone.utc)
    assert cache_is_fresh(now - timedelta(days=1), now=now)
    assert not cache_is_fresh(now - timedelta(days=31), now=now)
    assert not cache_is_fresh(None, now=now)


@pytest.mark.asyncio
async def test_fetch_doi_maps_crossref_payload():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/works/10.1109/cvpr.2016.90"
        assert "Nova-Agent" in request.headers["user-agent"]
        return httpx.Response(200, json=CROSSREF)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        result = await fetch_doi("10.1109/cvpr.2016.90", client=client)
    finally:
        await client.aclose()
    assert result["ok"] is True
    metadata = result["metadata"]
    assert metadata["title"] == "Deep residual learning for image recognition"
    assert metadata["year"] == 2016
    assert metadata["authors"][0] == "Kaiming He"
    assert metadata["pages"] == "770-778"


@pytest.mark.asyncio
async def test_fetch_doi_404_is_not_found_and_5xx_is_needs_review():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("missing"):
            return httpx.Response(404, json={"status": "error"})
        return httpx.Response(503, text="unavailable")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        missing = await fetch_doi("10.1000/missing", client=client)
        broken = await fetch_doi("10.1000/broken", client=client)
    finally:
        await client.aclose()
    assert missing["status"] == "not_found"
    assert broken["status"] == "needs_review"


@pytest.mark.asyncio
async def test_fetch_dois_deduplicates():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json=CROSSREF)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        results = await fetch_dois(
            ["10.1109/CVPR.2016.90", "10.1109/cvpr.2016.90"], client=client
        )
    finally:
        await client.aclose()
    assert len(calls) == 1
    assert list(results) == ["10.1109/cvpr.2016.90"]


@pytest.mark.asyncio
async def test_verify_metadata_caches_and_updates_citation_rows(monkeypatch):
    row = {
        "id": "citation-1",
        "kind": "reference",
        "raw": RAW_EN,
        "normalized": {"index": 1, "raw": RAW_EN},
        "doi": "",
        "metadata_status": "",
        "metadata": {},
        "metadata_fetched_at": None,
    }
    snapshot = {
        "project_id": "project-1",
        "document_id": "document-1",
        "references": [{"index": 1, "raw": RAW_EN}],
        "in_text": [],
        "citations": [row],
        "reference_section_found": True,
        "generated_at": datetime.now(timezone.utc),
    }

    async def fake_get_citations(user_id, project_id):
        return snapshot

    async def fake_query(sql, params=None):
        if "thesis_metadata_cache" in sql:
            return []
        raise AssertionError(f"unexpected query: {sql}")

    executed: list[tuple[str, tuple]] = []

    async def fake_transaction(statements):
        executed.extend(statements)

    monkeypatch.setattr(service, "get_citations", fake_get_citations)
    monkeypatch.setattr(service, "query", fake_query)
    monkeypatch.setattr(service, "transaction", fake_transaction)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=CROSSREF)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        await service.verify_citation_metadata(1, "project-1", client=client)
    finally:
        await client.aclose()

    cache_writes = [sql for sql, _ in executed if "thesis_metadata_cache" in sql]
    citation_writes = [sql for sql, _ in executed if "UPDATE thesis_citations" in sql]
    assert cache_writes
    assert citation_writes
    citation_params = next(params for sql, params in executed if "UPDATE thesis_citations" in sql)
    assert citation_params[1] == "verified"
    assert "10.1109/cvpr.2016.90" in citation_params[0]

"""Citation verification tests (DB access patched)."""
from unittest.mock import AsyncMock

import pytest

from app.core.agent import evidence as evidence_mod
from app.core.agent.evidence import verify_citations

FILES = [
    ("sample_project/app/tax.py", 16),
    ("sample_project/app/main.py", 20),
]


@pytest.fixture
def patched_query(monkeypatch):
    mock = AsyncMock(return_value=FILES)
    monkeypatch.setattr(evidence_mod, "query", mock)
    return mock


@pytest.mark.asyncio
async def test_verified_and_missing_citations(patched_query):
    text = (
        "实现位于 sample_project/app/tax.py:6-9，"
        "调用在 sample_project/app/main.py:14，"
        "另外 app/tax.py:12，"
        "还有一个不存在的 nope.py:3。"
    )
    report = await verify_citations(text, ["repo-uuid"], executed=False)
    statuses = {(c["path"], c["line"]): c["status"] for c in report["citations"]}
    assert statuses[("sample_project/app/tax.py", 6)] == "verified"
    assert statuses[("sample_project/app/main.py", 14)] == "verified"
    assert statuses[("app/tax.py", 12)] == "verified"          # suffix match
    assert statuses[("nope.py", 3)] == "missing"
    assert report["verified"] == 3 and report["missing"] == 1


@pytest.mark.asyncio
async def test_out_of_range_line(patched_query):
    report = await verify_citations("见 sample_project/app/tax.py:999", ["repo-uuid"], executed=True)
    assert report["citations"][0]["status"] == "out_of_range"
    assert report["out_of_range"] == 1
    assert report["executed"] is True


@pytest.mark.asyncio
async def test_no_repo_scope_is_unchecked(patched_query):
    report = await verify_citations("见 app/tax.py:6", [], executed=False)
    assert report["citations"][0]["status"] == "unchecked"
    assert report["skipped"] == 1


@pytest.mark.asyncio
async def test_no_citations_returns_empty_report(patched_query):
    report = await verify_citations("没有引用行号的普通回答。", ["repo-uuid"], executed=True)
    assert report["citations"] == []
    assert report["verified"] == 0 and report["executed"] is True
"""HTTP layer for resume profiles, facts and job versions."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.config import settings


def _client(user_id: int = 7):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.v1 import resume as resume_api
    from app.core.security.auth import get_current_user

    app = FastAPI()
    app.include_router(resume_api.router)
    app.dependency_overrides[get_current_user] = lambda: {"id": user_id}
    return TestClient(app)


@pytest.fixture()
def api(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "user_data_dir", str(tmp_path / "data"))
    return _client()


def _profile(client) -> dict:
    response = client.post(
        "/resume/profiles",
        json={"name": "张三", "headline": "计算机专业本科生", "contact": {"email": "a@example.com"}},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_create_profile_and_star_questions(api):
    profile = _profile(api)
    assert profile["name"] == "张三"
    assert api.get("/resume/profiles").json()["profiles"][0]["id"] == profile["id"]

    questions = api.get("/resume/questions", params={"audience": "student"}).json()
    assert len(questions["questions"]) == 5
    assert questions["questions"][0]["key"] == "situation"


def test_numeric_fact_without_evidence_needs_confirmation(api):
    profile = _profile(api)
    response = api.post(
        f"/resume/profiles/{profile['id']}/facts",
        json={
            "category": "项目",
            "title": "校园二手交易平台",
            "detail": "负责后端接口",
            "metrics": ["响应时间降低 40%"],
        },
    )
    assert response.status_code == 200, response.text
    fact = response.json()
    assert fact["status"] == "needs_confirmation"

    version = api.post(
        f"/resume/profiles/{profile['id']}/versions",
        json={"title": "后端开发实习", "fact_ids": [fact["id"]]},
    )
    assert version.status_code == 400
    assert "确认" in version.json()["detail"]


def test_fact_can_be_confirmed_then_used_in_job_version(api):
    profile = _profile(api)
    fact = api.post(
        f"/resume/profiles/{profile['id']}/facts",
        json={
            "category": "项目",
            "title": "校园二手交易平台",
            "detail": "负责订单接口与压测",
            "metrics": ["响应时间降低 40%"],
        },
    ).json()
    confirmed = api.patch(
        f"/resume/profiles/{profile['id']}/facts/{fact['id']}",
        json={"status": "evidence_linked", "evidence": "压测报告 docs/perf.md"},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "evidence_linked"

    other = api.post(
        f"/resume/profiles/{profile['id']}/facts",
        json={"category": "社团", "title": "摄影社", "status": "excluded"},
    ).json()
    version = api.post(
        f"/resume/profiles/{profile['id']}/versions",
        json={
            "title": "后端开发实习",
            "company": "某公司",
            "jd_text": "需要 Python 与性能优化经验",
            "fact_ids": [confirmed.json()["id"]],
            "template": "classic",
        },
    )
    assert version.status_code == 200, version.text
    body = version.json()
    assert body["jd_sha256"]
    assert "校园二手交易平台" in body["markdown"]
    assert "摄影社" not in body["markdown"]
    assert other["id"] not in body["fact_ids"]


def test_version_markdown_and_cross_user_isolation(api):
    profile = _profile(api)
    fact = api.post(
        f"/resume/profiles/{profile['id']}/facts",
        json={"category": "课程", "title": "数据库课程设计", "detail": "实现索引与查询优化"},
    ).json()
    version = api.post(
        f"/resume/profiles/{profile['id']}/versions",
        json={"title": "数据库工程师", "fact_ids": [fact["id"]]},
    ).json()

    markdown = api.get(f"/resume/versions/{version['id']}/markdown")
    assert markdown.status_code == 200
    assert "数据库课程设计" in markdown.text
    assert "人工智能" not in markdown.text

    other = _client(8)
    assert other.get(f"/resume/profiles/{profile['id']}").status_code == 404
    assert other.get(f"/resume/versions/{version['id']}").status_code == 404


def test_unknown_and_invalid_ids(api):
    assert api.get("/resume/profiles/not-a-real-id").status_code == 404
    assert api.post(
        "/resume/profiles/not-a-real-id/facts",
        json={"category": "项目", "title": "x"},
    ).status_code == 404
    assert api.get("/resume/versions/not-a-real-id").status_code == 404


def test_export_returns_unsupported_or_docx(api, tmp_path):
    profile = _profile(api)
    fact = api.post(
        f"/resume/profiles/{profile['id']}/facts",
        json={"category": "项目", "title": "课程项目", "detail": "完成一个命令行工具"},
    ).json()
    version = api.post(
        f"/resume/profiles/{profile['id']}/versions",
        json={"title": "初级开发", "fact_ids": [fact["id"]]},
    ).json()

    response = api.post(f"/resume/versions/{version['id']}/export", params={"format": "docx"})
    if response.status_code == 200:
        assert response.headers["content-type"].startswith(
            "application/vnd.openxmlformats"
        )
        assert response.content[:2] == b"PK"
    else:
        assert response.status_code == 409
        assert "工具" in response.json()["detail"]["message"]

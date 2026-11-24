"""HTTP layer for evidence packs and environment comparison."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.config import settings

VERIFICATION = {
    "steps": [
        {
            "name": "pytest", "command": "pytest -q", "required": True,
            "status": "passed", "exit_code": 0, "duration_ms": 1200,
            "stdout": "12 passed", "stderr": "",
        },
        {
            "name": "ruff", "command": "ruff check .", "required": True,
            "status": "failed", "exit_code": 1, "duration_ms": 300,
            "stdout": "", "stderr": "E501 line too long",
        },
    ],
    "report": {
        "workspace": {"commit": "abc1234", "branch": "main", "dirty": False},
        "environment": {
            "mode": "host", "isolation": "none", "network": "host",
            "workdir_scope": "host_repo", "env_scrubbed": False,
        },
    },
}


def _client(user_id: int = 7):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.v1 import evidence as evidence_api
    from app.core.security.auth import get_current_user

    app = FastAPI()
    app.include_router(evidence_api.router)
    app.dependency_overrides[get_current_user] = lambda: {"id": user_id}
    return TestClient(app)


@pytest.fixture()
def repo_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "coverage.txt").write_text("coverage 91%\n", encoding="utf-8")
    return root


@pytest.fixture()
def api(repo_root: Path, tmp_path: Path, monkeypatch):
    from app.api.v1 import evidence as evidence_api

    async def fake_get_repo(repo_id: str, user_id: int | None = None):
        if repo_id != "repo1" or user_id not in (None, 7):
            return None
        return {"id": "repo1", "user_id": 7, "root_path": str(repo_root)}

    async def fake_query(sql: str, params: tuple):
        return [(VERIFICATION,)] if "last_check" in sql else []

    monkeypatch.setattr(evidence_api, "get_repo", fake_get_repo)
    monkeypatch.setattr(evidence_api, "query", fake_query)
    monkeypatch.setattr(settings, "user_data_dir", str(tmp_path / "data"))
    return _client()


def _build(client, artifacts: list[str] | None = None) -> dict:
    response = client.post(
        "/evidence/repos/repo1/packs",
        json={"artifact_paths": artifacts or ["coverage.txt"]},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_build_pack_from_verification_facts(api):
    pack = _build(api)
    assert pack["commit"] == "abc1234"
    statuses = {claim["statement"]: claim["status"] for claim in pack["claims"]}
    assert any("pytest" in statement for statement in statuses)
    assert any("ruff" in statement for statement in statuses)
    assert any("ruff" in item for item in pack["unproven"])
    assert pack["artifacts"][0]["name"] == "coverage.txt"
    assert pack["manifest_sha256"].startswith("sha256:")
    assert len(pack["manifest_sha256"]) == 71


def test_list_get_and_verify_pack(api, repo_root: Path):
    pack = _build(api)
    listing = api.get("/evidence/packs").json()["packs"]
    assert listing[0]["pack_id"] == pack["pack_id"]
    assert listing[0]["unproven"] >= 1

    loaded = api.get(f"/evidence/packs/{pack['pack_id']}")
    assert loaded.status_code == 200
    assert loaded.json()["pack_id"] == pack["pack_id"]

    checked = api.post(f"/evidence/packs/{pack['pack_id']}/verify")
    assert checked.status_code == 200, checked.text
    assert checked.json()["ok"] is True

    (repo_root / "coverage.txt").write_text("coverage 10%\n", encoding="utf-8")
    tampered = api.post(f"/evidence/packs/{pack['pack_id']}/verify")
    assert tampered.status_code == 200
    assert tampered.json()["ok"] is False
    assert any("篡改" in item or "不一致" in item for item in tampered.json()["problems"])


def test_artifact_path_must_stay_inside_repo(api, tmp_path: Path):
    outside = tmp_path / "secret.txt"
    outside.write_text("nope", encoding="utf-8")
    response = api.post(
        "/evidence/repos/repo1/packs",
        json={"artifact_paths": ["../secret.txt"]},
    )
    assert response.status_code == 400
    assert "仓库目录" in response.json()["detail"]


def test_build_without_verification_is_refused(api, monkeypatch):
    from app.api.v1 import evidence as evidence_api

    async def empty_query(sql: str, params: tuple):
        return [(None,)]

    monkeypatch.setattr(evidence_api, "query", empty_query)
    response = api.post("/evidence/repos/repo1/packs", json={})
    assert response.status_code == 409
    assert "验证" in response.json()["detail"]


def test_cross_user_cannot_read_pack(api):
    pack = _build(api)
    other = _client(8)
    assert other.get(f"/evidence/packs/{pack['pack_id']}").status_code == 404


def test_compare_does_not_call_unknown_dimensions_equal(api):
    response = api.post(
        "/evidence/compare",
        json={
            "local": {"mode": "host", "os": "Windows", "arch": "AMD64", "isolation": "none"},
            "container": {"mode": "container", "os": "Linux", "arch": "x86_64", "isolation": "container"},
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "isolation" in body["different"]
    assert "tool_versions" in body["unknown"]
    assert body["identical"] is False
    assert "未记录不等于一致" in body["note"]

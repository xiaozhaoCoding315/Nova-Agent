"""HTTP layer for workspace document conversion."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.config import settings


def _client(user_id: int = 7):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.v1 import documents as documents_api
    from app.core.security.auth import get_current_user

    app = FastAPI()
    app.include_router(documents_api.router)
    app.dependency_overrides[get_current_user] = lambda: {"id": user_id}
    return TestClient(app)


@pytest.fixture()
def api(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "user_data_dir", str(tmp_path / "data"))
    monkeypatch.setattr(settings, "nova_mode", "server")
    return _client()


def _workspace(client) -> dict:
    response = client.post("/documents/workspaces", json={"title": "课程报告", "kind": "report"})
    assert response.status_code == 200, response.text
    return response.json()


def _write(client, workspace_id: str, content: str) -> None:
    read = client.get(
        f"/documents/workspaces/{workspace_id}/content",
        params={"path": "manuscripts/main.md"},
    ).json()
    response = client.put(
        f"/documents/workspaces/{workspace_id}/content",
        json={
            "path": "manuscripts/main.md",
            "content": content,
            "base_sha": read["sha256"],
        },
    )
    assert response.status_code == 200, response.text


def test_markdown_to_docx_with_fidelity(api):
    workspace = _workspace(api)
    _write(api, workspace["id"], "# 课程报告\n\n| 项 | 结果 |\n| --- | --- |\n| 测试 | 通过 |\n")
    response = api.post(
        f"/documents/workspaces/{workspace['id']}/convert",
        json={
            "source_path": "manuscripts/main.md",
            "target_format": "docx",
            "profile": "report",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    if body["status"] == "unsupported":
        assert "Pandoc" in " ".join(body["diagnostics"])
        return
    assert body["status"] in ("done", "partial", "lossy")
    assert body["output_path"].startswith("exports/")
    assert body["fidelity_path"].startswith("exports/")
    assert body["fidelity"]["target"].endswith(".docx")
    assert body["fidelity"]["profile"] == "report"


def test_missing_source_and_traversal_are_rejected(api, tmp_path: Path):
    workspace = _workspace(api)
    missing = api.post(
        f"/documents/workspaces/{workspace['id']}/convert",
        json={"source_path": "manuscripts/missing.md", "target_format": "docx"},
    )
    assert missing.status_code == 404

    outside = tmp_path / "outside.md"
    outside.write_text("# outside", encoding="utf-8")
    escaped = api.post(
        f"/documents/workspaces/{workspace['id']}/convert",
        json={"source_path": "../outside.md", "target_format": "docx"},
    )
    assert escaped.status_code == 400


def test_pdf_source_is_not_reversibly_edited(api):
    workspace = _workspace(api)
    _write(api, workspace["id"], "# 报告\n\n正文\n")
    # A real PDF is not required: the pair is rejected before tool detection.
    pdf = workspace["root"] or ""
    assert pdf == ""  # server mode hides host paths
    exports = Path(settings.user_data_dir) / "7" / "documents" / workspace["id"] / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    (exports / "sample.pdf").write_bytes(b"%PDF-1.4\n")
    response = api.post(
        f"/documents/workspaces/{workspace['id']}/convert",
        json={"source_path": "exports/sample.pdf", "target_format": "docx"},
    )
    assert response.status_code == 400
    assert "PDF" in response.json()["detail"]


def test_unknown_profile_is_validated(api):
    workspace = _workspace(api)
    response = api.post(
        f"/documents/workspaces/{workspace['id']}/convert",
        json={
            "source_path": "manuscripts/main.md",
            "target_format": "docx",
            "profile": "magazine",
        },
    )
    assert response.status_code == 422

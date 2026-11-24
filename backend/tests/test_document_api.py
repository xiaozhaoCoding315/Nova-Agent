"""HTTP layer for document workspaces (isolated router, auth overridden)."""
from __future__ import annotations

import shutil
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


def _create(client, title: str = "课程报告") -> dict:
    response = client.post("/documents/workspaces", json={"title": title, "kind": "report"})
    assert response.status_code == 200, response.text
    return response.json()


def test_create_list_and_read(api):
    workspace = _create(api)
    assert workspace["title"] == "课程报告"
    assert workspace["root"] is None  # server mode never exposes the host path

    listing = api.get("/documents/workspaces").json()["workspaces"]
    assert [item["id"] for item in listing] == [workspace["id"]]

    files = api.get(f"/documents/workspaces/{workspace['id']}/files").json()["files"]
    assert [item["path"] for item in files] == ["manuscripts/main.md"]

    content = api.get(
        f"/documents/workspaces/{workspace['id']}/content",
        params={"path": "manuscripts/main.md"},
    ).json()
    assert content["content"].startswith("# 课程报告")


def test_write_conflict_and_versions(api, tmp_path: Path):
    workspace = _create(api)
    base = f"/documents/workspaces/{workspace['id']}"
    read = api.get(f"{base}/content", params={"path": "manuscripts/main.md"}).json()

    saved = api.put(f"{base}/content", json={
        "path": "manuscripts/main.md",
        "content": "# 课程报告\n\n第一版\n",
        "base_sha": read["sha256"],
    })
    assert saved.status_code == 200, saved.text
    assert saved.json()["version"] is not None  # the initial content is snapshotted

    # External edit: stale base must produce 409 with the current hash.
    from app.core.documents.store import get_workspace

    workspace_dir = get_workspace(7, workspace["id"]).root
    (workspace_dir / "manuscripts" / "main.md").write_text("# 外部修改\n", encoding="utf-8")
    conflict = api.put(f"{base}/content", json={
        "path": "manuscripts/main.md", "content": "# 覆盖\n", "base_sha": saved.json()["sha256"],
    })
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["current_sha"]

    current = api.get(f"{base}/content", params={"path": "manuscripts/main.md"}).json()
    versions = api.get(f"{base}/versions", params={"path": "manuscripts/main.md"}).json()["versions"]
    assert len(versions) == 1

    restored = api.post(
        f"{base}/versions/{versions[0]['version_id']}/restore",
        json={"path": "manuscripts/main.md", "base_sha": current["sha256"]},
    )
    assert restored.status_code == 200, restored.text
    assert api.get(
        f"{base}/content", params={"path": "manuscripts/main.md"},
    ).json()["content"] == read["content"]


def test_rejects_traversal_and_unknown_workspace(api):
    workspace = _create(api)
    response = api.get(
        f"/documents/workspaces/{workspace['id']}/content",
        params={"path": "manuscripts/../../secret.md"},
    )
    assert response.status_code == 400
    assert "跳出" in response.json()["detail"]

    assert api.get("/documents/workspaces/deadbeefdeadbeef").status_code == 404


def test_other_user_cannot_read(api, tmp_path: Path, monkeypatch):
    workspace = _create(api)
    other = _client(8)
    assert other.get(f"/documents/workspaces/{workspace['id']}").status_code == 404
    assert other.get("/documents/workspaces").json()["workspaces"] == []


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="Pandoc is not installed")
def test_export_and_download(api):
    workspace = _create(api)
    base = f"/documents/workspaces/{workspace['id']}"
    result = api.post(f"{base}/export", json={"path": "manuscripts/main.md", "format": "docx"})
    assert result.status_code == 200, result.text
    payload = result.json()
    assert payload["status"] == "done"
    assert payload["fidelity"]["status"] == "exact"

    download = api.get(f"{base}/download", params={"path": payload["path"]})
    assert download.status_code == 200
    assert download.content[:2] == b"PK"  # DOCX is a ZIP container
    assert download.headers["content-disposition"]


def test_download_rejects_non_export_path(api):
    workspace = _create(api)
    base = f"/documents/workspaces/{workspace['id']}"
    response = api.get(f"{base}/download", params={"path": "manuscripts/main.md"})
    assert response.status_code == 400


def test_delete_workspace(api):
    workspace = _create(api)
    assert api.delete(f"/documents/workspaces/{workspace['id']}").status_code == 200
    assert api.get(f"/documents/workspaces/{workspace['id']}").status_code == 404


def test_draft_is_limited_to_report_workspaces(api):
    response = api.post("/documents/workspaces", json={"title": "论文", "kind": "thesis"})
    workspace = response.json()
    draft = api.post(
        f"/documents/workspaces/{workspace['id']}/draft",
        json={"requirements": "写一份系统设计报告"},
    )
    assert draft.status_code == 400
    assert "报告工作区" in draft.json()["detail"]


def test_draft_writes_markdown_and_records_usage(api, monkeypatch):
    from app.api.v1 import documents as documents_api
    import app.core.llm.factory as factory_mod
    import app.core.llm.usage as usage_mod

    class FakeLLM:
        async def astream_with_tools(self, messages, tools, **kwargs):
            assert messages[0]["role"] == "system"
            assert "待补充" in messages[0]["content"]
            yield {"type": "content", "content": "# 课程报告\n\n## 背景\n\n待补充\n"}
            yield {"type": "usage", "usage": {"prompt_tokens": 3, "completion_tokens": 4}}

    async def fake_get_llm(user_id=None, **kwargs):
        return FakeLLM()

    async def fake_budget(user=None, **kwargs):
        return None

    recorded = []

    async def fake_record(*args, **kwargs):
        recorded.append(kwargs.get("source"))

    monkeypatch.setattr(factory_mod, "get_llm", fake_get_llm)
    monkeypatch.setattr(usage_mod, "record_usage", fake_record)
    monkeypatch.setattr(documents_api, "ensure_token_budget", fake_budget)

    workspace = _create(api)
    base = f"/documents/workspaces/{workspace['id']}"
    response = api.post(f"{base}/draft", json={
        "requirements": "写一份课程设计报告，课程是数据库系统。",
        "path": "manuscripts/report.md",
        "word_count": 2000,
    })
    assert response.status_code == 200, response.text
    assert response.json()["content"].startswith("# 课程报告")
    assert recorded == ["documents"]

    files = api.get(f"{base}/files").json()["files"]
    assert "manuscripts/report.md" in [item["path"] for item in files]

    # The draft never silently overwrites an existing manuscript.
    again = api.post(f"{base}/draft", json={
        "requirements": "再写一份", "path": "manuscripts/report.md",
    })
    assert again.status_code == 409

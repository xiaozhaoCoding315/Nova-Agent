"""GitHub delivery: explicit authorization, draft PRs and the review loop."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.core.github import service as github_service
from app.core.github.service import GitHubError, parse_remote


def _client(user_id: int = 7):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.v1 import github as github_api
    from app.core.security.auth import get_current_user

    app = FastAPI()
    app.include_router(github_api.router)
    app.dependency_overrides[get_current_user] = lambda: {"id": user_id}
    return TestClient(app)


@pytest.fixture()
def api(monkeypatch):
    from app.api.v1 import github as github_api

    async def fake_get_repo(repo_id: str, user_id: int | None = None):
        if repo_id != "repo1":
            return None
        return {"id": "repo1", "user_id": 7, "name": "demo", "root_path": str(Path.cwd())}

    monkeypatch.setattr(github_api, "get_repo", fake_get_repo)
    return _client()


def test_parse_remote_accepts_https_and_ssh():
    assert parse_remote("https://github.com/alice/demo.git")["full_name"] == "alice/demo"
    assert parse_remote("git@github.com:alice/demo.git")["full_name"] == "alice/demo"
    assert parse_remote("ssh://git@github.com/alice/demo")["full_name"] == "alice/demo"
    with pytest.raises(GitHubError):
        parse_remote("https://gitlab.com/alice/demo.git")
    with pytest.raises(GitHubError):
        parse_remote("not a remote")


def test_create_requires_explicit_authorization(monkeypatch):
    called = {"token": False}

    async def fake_token(user_id: int):
        called["token"] = True
        return "t"

    monkeypatch.setattr(github_service, "_token", fake_token)
    with pytest.raises(GitHubError) as exc:
        import asyncio

        asyncio.run(github_service.create_draft_pr(
            7, "repo1", Path("."), title="demo", authorization="",
        ))
    assert "授权" in str(exc.value)
    assert called["token"] is False


def test_connect_encrypts_token_and_status_hides_it(monkeypatch):
    inserted: dict = {}

    async def fake_request(method: str, path: str, token: str, **kwargs):
        assert method == "GET" and path == "/user"
        return {"login": "alice"}, {"x-oauth-scopes": "repo"}

    async def fake_execute(sql: str, params: tuple):
        inserted["params"] = params
        return []

    async def fake_query(sql: str, params: tuple):
        return [("alice", "repo", "2026-01-01", "2026-01-02")]

    monkeypatch.setattr(github_service, "_request", fake_request)
    monkeypatch.setattr(github_service, "execute", fake_execute)
    monkeypatch.setattr(github_service, "query", fake_query)

    import asyncio

    connected = asyncio.run(github_service.connect_token(7, "ghp_example_token_123"))
    assert connected == {"connected": True, "login": "alice", "scopes": "repo"}
    assert inserted["params"][2] != "ghp_example_token_123"

    status = asyncio.run(github_service.connection_status(7))
    assert status["connected"] is True
    assert "token" not in status
    assert status["login"] == "alice"


def test_create_draft_pr_requires_pushed_branch_and_never_merges(monkeypatch):
    calls: list[tuple[str, str, dict]] = []
    inserted: dict = {}

    async def fake_token(user_id: int):
        return "token"

    async def fake_request(method: str, path: str, token: str, **kwargs):
        calls.append((method, path, kwargs))
        if method == "GET" and path.startswith("/repos/") and "/branches/" not in path:
            return {"default_branch": "main"}, {}
        if method == "GET" and "/branches/" in path:
            return {"commit": {"sha": "a" * 40}}, {}
        if method == "POST" and path.endswith("/pulls"):
            return {"number": 12, "html_url": "https://github.com/alice/demo/pull/12", "state": "open"}, {}
        raise AssertionError(f"unexpected call {method} {path}")

    async def fake_execute(sql: str, params: tuple):
        inserted["params"] = params
        return []

    monkeypatch.setattr(github_service, "_token", fake_token)
    monkeypatch.setattr(github_service, "repo_remote", lambda root: {
        "host": "github.com", "owner": "alice", "repo": "demo",
        "full_name": "alice/demo", "branch": "feat/x",
    })
    monkeypatch.setattr(github_service, "_request", fake_request)
    monkeypatch.setattr(github_service, "execute", fake_execute)
    monkeypatch.setattr(github_service, "_local_head", lambda root: "a" * 40)

    import asyncio

    result = asyncio.run(github_service.create_draft_pr(
        7, "repo1", Path("."), title="Add x", body="body",
        authorization="create-draft-pr",
    ))
    assert result["number"] == 12
    assert result["draft"] is True
    post = [call for call in calls if call[0] == "POST"]
    assert len(post) == 1
    assert post[0][2]["json_body"]["draft"] is True
    assert post[0][2]["json_body"]["head"] == "feat/x"
    assert not any("merge" in path for _, path, _ in calls)


def test_create_draft_pr_refuses_unpushed_branch(monkeypatch):
    async def fake_token(user_id: int):
        return "token"

    async def fake_request(method: str, path: str, token: str, **kwargs):
        if "/branches/" in path:
            raise GitHubError("GitHub 返回 404：Branch not found")
        return {"default_branch": "main"}, {}

    monkeypatch.setattr(github_service, "_token", fake_token)
    monkeypatch.setattr(github_service, "repo_remote", lambda root: {
        "host": "github.com", "owner": "alice", "repo": "demo",
        "full_name": "alice/demo", "branch": "feat/x",
    })
    monkeypatch.setattr(github_service, "_request", fake_request)

    import asyncio

    with pytest.raises(GitHubError) as exc:
        asyncio.run(github_service.create_draft_pr(
            7, "repo1", Path("."), title="Add x",
            authorization="create-draft-pr",
        ))
    assert "推送" in str(exc.value)


def test_create_draft_pr_refuses_when_local_head_is_not_pushed(monkeypatch):
    async def fake_token(user_id: int):
        return "token"

    async def fake_request(method: str, path: str, token: str, **kwargs):
        if method == "GET" and "/branches/" in path:
            # The branch is URL-encoded, so feat/x arrives as feat%2Fx.
            return {"commit": {"sha": "b" * 40}}, {}
        if method == "GET" and path.startswith("/repos/"):
            return {"default_branch": "main"}, {}
        raise AssertionError(f"unexpected call {method} {path}")

    monkeypatch.setattr(github_service, "_token", fake_token)
    monkeypatch.setattr(github_service, "repo_remote", lambda root: {
        "host": "github.com", "owner": "alice", "repo": "demo",
        "full_name": "alice/demo", "branch": "feat/x",
    })
    monkeypatch.setattr(github_service, "_request", fake_request)
    monkeypatch.setattr(github_service, "_local_head", lambda root: "a" * 40)

    import asyncio

    with pytest.raises(GitHubError) as exc:
        asyncio.run(github_service.create_draft_pr(
            7, "repo1", Path("."), title="Add x",
            authorization="create-draft-pr",
        ))
    assert "不一致" in str(exc.value)


def test_pr_status_reports_ci_and_reviews_without_merge(monkeypatch):
    async def fake_query(sql: str, params: tuple):
        return [("alice", "demo", "https://example/1", "title", "open", True)]

    async def fake_token(user_id: int):
        return "token"

    async def fake_request(method: str, path: str, token: str, **kwargs):
        if path == "/repos/alice/demo/pulls/1":
            return {
                "html_url": "https://github.com/alice/demo/pull/1",
                "title": "Add x", "state": "open", "draft": True,
                "mergeable": True, "mergeable_state": "clean",
                "head": {"ref": "feat/x", "sha": "abc123"},
                "base": {"ref": "main"}, "updated_at": "2026-01-01T00:00:00Z",
            }, {}
        if path.endswith("/check-runs"):
            return {"check_runs": [{
                "name": "ci", "status": "completed", "conclusion": "failure",
                "html_url": "https://ci/1",
            }]}, {}
        if path.endswith("/status"):
            return {"statuses": [{
                "context": "build", "state": "success", "target_url": "https://ci/2",
            }]}, {}
        if path.endswith("/reviews"):
            return [{
                "id": 1, "user": {"login": "bob"}, "state": "CHANGES_REQUESTED",
                "body": "请补测试", "submitted_at": "2026-01-01T01:00:00Z",
            }], {}
        if path.endswith("/pulls/1/comments"):
            return [{
                "id": 2, "user": {"login": "bob"}, "body": "这里要改",
                "path": "src/x.ts", "line": 4, "created_at": "2026-01-01T01:01:00Z",
            }], {}
        if path.endswith("/issues/1/comments"):
            return [{
                "id": 3, "user": {"login": "carol"}, "body": "记得更新文档",
                "created_at": "2026-01-01T01:02:00Z",
            }], {}
        raise AssertionError(path)

    monkeypatch.setattr(github_service, "query", fake_query)
    monkeypatch.setattr(github_service, "_token", fake_token)
    monkeypatch.setattr(github_service, "_request", fake_request)

    import asyncio

    data = asyncio.run(github_service.pr_status(7, "repo1", 1))
    assert data["auto_merge"] is False
    assert data["mergeable_state"] == "clean"
    assert {item["conclusion"] for item in data["checks"]} == {"failure", "success"}
    assert data["reviews"][0]["state"] == "CHANGES_REQUESTED"
    assert {item["body"] for item in data["comments"]} == {"这里要改", "记得更新文档"}
    assert "合并" in data["note"]


def test_api_refuses_pr_without_authorization(api, monkeypatch):
    from app.api.v1 import github as github_api

    async def fake_create(*args, **kwargs):
        raise GitHubError("需要明确授权才能创建 draft PR")

    monkeypatch.setattr(github_api, "create_draft_pr", fake_create)
    response = api.post(
        "/github/repos/repo1/prs",
        json={"title": "demo", "authorization": ""},
    )
    assert response.status_code == 403
    assert "授权" in response.json()["detail"]


def test_api_connect_and_status(api, monkeypatch):
    from app.api.v1 import github as github_api

    async def fake_connect(user_id: int, token: str):
        assert user_id == 7
        return {"connected": True, "login": "alice", "scopes": "repo"}

    async def fake_status(user_id: int):
        return {"connected": True, "login": "alice", "scopes": "repo"}

    monkeypatch.setattr(github_api, "connect_token", fake_connect)
    monkeypatch.setattr(github_api, "connection_status", fake_status)
    connected = api.post("/github/connect", json={"token": "ghp_example_token_123"})
    assert connected.status_code == 200
    assert api.get("/github/status").json()["login"] == "alice"


def test_status_envelope_has_no_write_paths():
    """The status payload shape never grows an auto-merge/merge field."""
    from app.core.github import service

    source = Path(service.__file__).read_text(encoding="utf-8")
    assert '"/merge"' not in source
    assert "'merge'" not in source

"""GitHub REST operations used by the PR/CI/review loop.

Only draft PR creation writes remotely, and only when the request carries the
explicit ``create-draft-pr`` authorization.  There is no merge or push code in
this module.
"""
from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from app.config import settings
from app.core.git_ops.service import _run_git
from app.core.llm.user_settings import decrypt_key, encrypt_key
from app.db import execute, query

AUTHORIZATION_PHRASE = "create-draft-pr"
_API_VERSION = "2022-11-28"
_HTTPS_REMOTE = re.compile(
    r"^https?://(?:[^@/]+@)?(?P<host>[^/]+)/(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$",
    re.IGNORECASE,
)
_SSH_REMOTE = re.compile(
    r"^(?:ssh://)?git@(?P<host>[^:/]+)[:/](?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$",
    re.IGNORECASE,
)


class GitHubError(Exception):
    """A GitHub operation failed; the message is safe to show to the user."""


def _error_message(status: int, data: Any) -> str:
    if isinstance(data, dict):
        message = str(data.get("message") or "").strip()
        if message:
            return f"GitHub 返回 {status}：{message[:300]}"
    return f"GitHub 返回 {status}"


async def _request(
    method: str,
    path: str,
    token: str,
    *,
    json_body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> tuple[Any, httpx.Headers]:
    base = settings.github_api_url.rstrip("/")
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": _API_VERSION,
        "User-Agent": "Nova-Agent",
    }
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
            response = await client.request(
                method, f"{base}{path}", headers=headers,
                json=json_body, params=params,
            )
    except httpx.HTTPError as exc:
        raise GitHubError(f"连接 GitHub 失败：{type(exc).__name__}") from exc
    try:
        data = response.json()
    except ValueError:
        data = {}
    if response.status_code >= 400:
        raise GitHubError(_error_message(response.status_code, data))
    return data, response.headers


def _decrypt(token_enc: str) -> str:
    try:
        return decrypt_key(token_enc)
    except ValueError as exc:
        raise GitHubError("GitHub token 无法解密，请重新连接") from exc


async def _token(user_id: int) -> str:
    rows = await query(
        "SELECT token_enc FROM user_github_connections WHERE user_id = %s",
        (user_id,),
    )
    if not rows:
        raise GitHubError("还没有连接 GitHub")
    return _decrypt(str(rows[0][0]))


async def connect_token(user_id: int, token: str) -> dict[str, Any]:
    value = (token or "").strip()
    if not value:
        raise GitHubError("请填写 GitHub token")
    if len(value) > 500:
        raise GitHubError("GitHub token 过长")
    data, headers = await _request("GET", "/user", value)
    if not isinstance(data, dict) or not data.get("login"):
        raise GitHubError("这个 token 不能读取 GitHub 用户信息")
    login = str(data.get("login") or "")[:80]
    scopes = str(headers.get("x-oauth-scopes") or "")[:300]
    await execute(
        """
        INSERT INTO user_github_connections (user_id, login, token_enc, scopes)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (user_id) DO UPDATE SET
            login = EXCLUDED.login,
            token_enc = EXCLUDED.token_enc,
            scopes = EXCLUDED.scopes,
            updated_at = now()
        """,
        (user_id, login, encrypt_key(value), scopes),
    )
    return {"connected": True, "login": login, "scopes": scopes}


async def connection_status(user_id: int) -> dict[str, Any]:
    rows = await query(
        "SELECT login, scopes, created_at, updated_at "
        "FROM user_github_connections WHERE user_id = %s",
        (user_id,),
    )
    if not rows:
        return {"connected": False, "login": "", "scopes": "", "created_at": ""}
    row = rows[0]
    return {
        "connected": True,
        "login": row[0],
        "scopes": row[1],
        "created_at": str(row[2] or ""),
        "updated_at": str(row[3] or ""),
    }


async def disconnect(user_id: int) -> dict[str, Any]:
    await execute("DELETE FROM user_github_connections WHERE user_id = %s", (user_id,))
    return {"connected": False}


def parse_remote(url: str) -> dict[str, str]:
    """Parse an HTTPS or SSH GitHub remote into owner/repo/host."""
    value = (url or "").strip()
    match = _HTTPS_REMOTE.match(value) or _SSH_REMOTE.match(value)
    if not match:
        raise GitHubError("仓库的 origin 不是可识别的 GitHub 地址")
    host = match.group("host").lower()
    if host not in ("github.com", "www.github.com"):
        raise GitHubError("目前只支持 github.com 仓库")
    return {
        "host": "github.com",
        "owner": match.group("owner"),
        "repo": match.group("repo"),
        "full_name": f"{match.group('owner')}/{match.group('repo')}",
    }


def repo_remote(root: Path) -> dict[str, Any]:
    """Read ``remote.origin.url`` from the repo; no network access."""
    result = _run_git(Path(root), "remote", "get-url", "origin")
    url = (result.stdout or "").strip()
    if result.returncode != 0 or not url:
        raise GitHubError("仓库没有 origin；先添加 GitHub 远程地址")
    parsed = parse_remote(url)
    branch = _run_git(Path(root), "rev-parse", "--abbrev-ref", "HEAD")
    current = (branch.stdout or "").strip()
    parsed["branch"] = "" if current in ("", "HEAD") else current
    return parsed


async def _default_branch(token: str, owner: str, repo: str) -> str:
    data, _ = await _request("GET", f"/repos/{owner}/{repo}", token)
    return str((data or {}).get("default_branch") or "main")


async def _branch_sha(token: str, owner: str, repo: str, branch: str) -> str:
    try:
        data, _ = await _request(
            "GET", f"/repos/{owner}/{repo}/branches/{quote(branch, safe='')}", token,
        )
    except GitHubError as exc:
        if "404" in str(exc):
            return ""
        raise
    commit = (data or {}).get("commit") if isinstance(data, dict) else None
    return str((commit or {}).get("sha") or "")


def _local_head(root: Path) -> str:
    result = _run_git(Path(root), "rev-parse", "HEAD")
    return (result.stdout or "").strip() if result.returncode == 0 else ""


async def create_draft_pr(
    user_id: int,
    repo_id: str,
    root: Path,
    *,
    title: str,
    body: str = "",
    base: str = "",
    authorization: str = "",
) -> dict[str, Any]:
    """Create a draft PR after an explicit per-request authorization."""
    if authorization != AUTHORIZATION_PHRASE:
        raise GitHubError("需要明确授权才能创建 draft PR")
    clean_title = (title or "").strip()
    if not clean_title:
        raise GitHubError("请填写 PR 标题")
    if len(clean_title) > 200:
        raise GitHubError("PR 标题过长")
    token = await _token(user_id)
    remote = repo_remote(root)
    branch = remote.get("branch") or ""
    if not branch:
        raise GitHubError("当前是 detached HEAD；先切到要提交的分支")
    owner, repo = remote["owner"], remote["repo"]
    target_base = (base or "").strip() or await _default_branch(token, owner, repo)
    if target_base == branch:
        raise GitHubError("head 与 base 不能是同一个分支")
    remote_sha = await _branch_sha(token, owner, repo, branch)
    if not remote_sha:
        raise GitHubError(f"远端还没有分支 {branch}；先推送分支，再创建 PR")
    head_sha = _local_head(root)
    if not head_sha:
        raise GitHubError("无法读取本地 HEAD；先在要提交的分支上提交")
    if head_sha != remote_sha:
        raise GitHubError(
            f"本地 HEAD 与远端分支 {branch} 不一致；先提交并推送，再创建 PR"
        )

    data, _ = await _request(
        "POST", f"/repos/{owner}/{repo}/pulls", token,
        json_body={
            "title": clean_title,
            "head": branch,
            "base": target_base,
            "body": (body or "")[:20000],
            "draft": True,
        },
    )
    if not isinstance(data, dict) or not data.get("number"):
        raise GitHubError("GitHub 没有返回 PR 编号")
    number = int(data["number"])
    html_url = str(data.get("html_url") or "")
    await execute(
        """
        INSERT INTO github_pull_requests
            (id, user_id, repo_id, owner, repo, number, url, title, head, base, draft, state)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE, %s)
        ON CONFLICT (repo_id, number) DO UPDATE SET
            url = EXCLUDED.url, title = EXCLUDED.title, head = EXCLUDED.head,
            base = EXCLUDED.base, state = EXCLUDED.state, updated_at = now()
        """,
        (
            str(uuid.uuid4()), user_id, repo_id, owner, repo[:120], number,
            html_url, clean_title[:300], branch[:200], target_base[:200],
            str(data.get("state") or "open")[:20],
        ),
    )
    return {
        "number": number,
        "url": html_url,
        "title": clean_title,
        "draft": True,
        "head": branch,
        "base": target_base,
        "state": str(data.get("state") or "open"),
        "authorized": True,
    }


async def list_pull_requests(user_id: int, repo_id: str) -> list[dict[str, Any]]:
    rows = await query(
        "SELECT number, url, title, head, base, draft, state, owner, repo, created_at "
        "FROM github_pull_requests WHERE user_id = %s AND repo_id = %s "
        "ORDER BY created_at DESC LIMIT 50",
        (user_id, repo_id),
    )
    return [
        {
            "number": int(row[0]),
            "url": row[1],
            "title": row[2],
            "head": row[3],
            "base": row[4],
            "draft": bool(row[5]),
            "state": row[6],
            "owner": row[7],
            "repo": row[8],
            "created_at": str(row[9] or ""),
        }
        for row in rows
    ]


def _check_row(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": str(raw.get("name") or "")[:120],
        "status": str(raw.get("status") or "")[:20],
        "conclusion": str(raw.get("conclusion") or "")[:20],
        "url": str(raw.get("html_url") or raw.get("details_url") or "")[:500],
        "source": "check_run",
    }


def _status_row(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": str(raw.get("context") or "")[:120],
        "status": "completed",
        "conclusion": str(raw.get("state") or "")[:20],
        "url": str(raw.get("target_url") or "")[:500],
        "source": "status",
    }


def _review_row(raw: dict[str, Any]) -> dict[str, Any]:
    user = raw.get("user") if isinstance(raw.get("user"), dict) else {}
    return {
        "id": raw.get("id"),
        "user": str(user.get("login") or "")[:80],
        "state": str(raw.get("state") or "")[:30],
        "body": str(raw.get("body") or "")[:2000],
        "submitted_at": str(raw.get("submitted_at") or "")[:40],
        "url": str(raw.get("html_url") or "")[:500],
    }


def _comment_row(raw: dict[str, Any]) -> dict[str, Any]:
    user = raw.get("user") if isinstance(raw.get("user"), dict) else {}
    return {
        "id": raw.get("id"),
        "user": str(user.get("login") or "")[:80],
        "body": str(raw.get("body") or "")[:2000],
        "path": str(raw.get("path") or "")[:500],
        "line": raw.get("line"),
        "created_at": str(raw.get("created_at") or "")[:40],
        "url": str(raw.get("html_url") or "")[:500],
    }


async def pr_status(user_id: int, repo_id: str, number: int) -> dict[str, Any]:
    rows = await query(
        "SELECT owner, repo, url, title, state, draft FROM github_pull_requests "
        "WHERE user_id = %s AND repo_id = %s AND number = %s",
        (user_id, repo_id, int(number)),
    )
    if not rows:
        raise GitHubError("这个 PR 不在本机的交付记录里")
    owner, repo, url, title, state, draft = rows[0]
    token = await _token(user_id)
    pull, _ = await _request("GET", f"/repos/{owner}/{repo}/pulls/{int(number)}", token)
    if not isinstance(pull, dict):
        raise GitHubError("GitHub 没有返回 PR 详情")
    head = pull.get("head") if isinstance(pull.get("head"), dict) else {}
    head_sha = str(head.get("sha") or "")
    checks: list[dict[str, Any]] = []
    if head_sha:
        runs, _ = await _request(
            "GET", f"/repos/{owner}/{repo}/commits/{head_sha}/check-runs", token,
            params={"per_page": 50},
        )
        for item in (runs or {}).get("check_runs") or []:
            if isinstance(item, dict):
                checks.append(_check_row(item))
        combined, _ = await _request(
            "GET", f"/repos/{owner}/{repo}/commits/{head_sha}/status", token,
        )
        for item in (combined or {}).get("statuses") or []:
            if isinstance(item, dict):
                checks.append(_status_row(item))
    reviews_data, _ = await _request(
        "GET", f"/repos/{owner}/{repo}/pulls/{int(number)}/reviews", token,
    )
    review_comments, _ = await _request(
        "GET", f"/repos/{owner}/{repo}/pulls/{int(number)}/comments", token,
    )
    issue_comments, _ = await _request(
        "GET", f"/repos/{owner}/{repo}/issues/{int(number)}/comments", token,
    )
    reviews = [
        _review_row(item) for item in (reviews_data or []) if isinstance(item, dict)
    ]
    comments = [
        _comment_row(item)
        for item in list(review_comments or []) + list(issue_comments or [])
        if isinstance(item, dict)
    ]
    return {
        "number": int(number),
        "url": str(pull.get("html_url") or url),
        "title": str(pull.get("title") or title),
        "state": str(pull.get("state") or state),
        "draft": bool(pull.get("draft", draft)),
        "mergeable": pull.get("mergeable"),
        "mergeable_state": str(pull.get("mergeable_state") or ""),
        "head": str(head.get("ref") or ""),
        "head_sha": head_sha,
        "base": str((pull.get("base") or {}).get("ref") or ""),
        "updated_at": str(pull.get("updated_at") or ""),
        "checks": checks,
        "reviews": reviews,
        "comments": comments,
        "auto_merge": False,
        "note": "这里只读 CI 与评审；合并和推送主分支仍由用户在 GitHub 上决定。",
    }


__all__ = [
    "AUTHORIZATION_PHRASE",
    "GitHubError",
    "connect_token",
    "connection_status",
    "create_draft_pr",
    "disconnect",
    "list_pull_requests",
    "parse_remote",
    "pr_status",
    "repo_remote",
]

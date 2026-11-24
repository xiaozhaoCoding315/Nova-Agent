"""GitHub draft-PR, CI and review endpoints.

There is no merge endpoint and no automatic remote write: creating a draft PR
requires the literal authorization phrase from the user's request.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.github.service import (
    GitHubError,
    connect_token,
    connection_status,
    create_draft_pr,
    disconnect,
    list_pull_requests,
    pr_status,
    repo_remote,
)
from app.core.indexing.pipeline import get_repo
from app.core.security.auth import get_current_user

router = APIRouter()


class GitHubConnectIn(BaseModel):
    token: str = Field(min_length=10, max_length=500)


class DraftPullRequestIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(default="", max_length=20000)
    base: str = Field(default="", max_length=200)
    authorization: str = Field(default="", max_length=40)


async def _repo_or_404(repo_id: str, user_id: int) -> dict:
    repo = await get_repo(repo_id, user_id)
    if not repo:
        raise HTTPException(status_code=404, detail="仓库不存在")
    return repo


@router.get("/github/status")
async def github_status(user: dict = Depends(get_current_user)):
    return await connection_status(user["id"])


@router.post("/github/connect")
async def github_connect(
    body: GitHubConnectIn,
    user: dict = Depends(get_current_user),
):
    try:
        return await connect_token(user["id"], body.token)
    except GitHubError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/github/disconnect")
async def github_disconnect(user: dict = Depends(get_current_user)):
    return await disconnect(user["id"])


@router.get("/github/repos/{repo_id}/remote")
async def github_remote(
    repo_id: str,
    user: dict = Depends(get_current_user),
):
    repo = await _repo_or_404(repo_id, user["id"])
    try:
        return repo_remote(Path(repo["root_path"]))
    except GitHubError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/github/repos/{repo_id}/prs")
async def github_pull_requests(
    repo_id: str,
    user: dict = Depends(get_current_user),
):
    await _repo_or_404(repo_id, user["id"])
    return {"pull_requests": await list_pull_requests(user["id"], repo_id)}


@router.post("/github/repos/{repo_id}/prs")
async def github_create_pull_request(
    repo_id: str,
    body: DraftPullRequestIn,
    user: dict = Depends(get_current_user),
):
    repo = await _repo_or_404(repo_id, user["id"])
    try:
        return await create_draft_pr(
            user["id"],
            repo_id,
            Path(repo["root_path"]),
            title=body.title,
            body=body.body,
            base=body.base,
            authorization=body.authorization,
        )
    except GitHubError as exc:
        status = 403 if "授权" in str(exc) else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc


@router.get("/github/repos/{repo_id}/prs/{number}")
async def github_pull_request_status(
    repo_id: str,
    number: int,
    user: dict = Depends(get_current_user),
):
    await _repo_or_404(repo_id, user["id"])
    if number <= 0:
        raise HTTPException(status_code=400, detail="PR 编号不正确")
    try:
        return await pr_status(user["id"], repo_id, number)
    except GitHubError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


__all__ = ["router"]

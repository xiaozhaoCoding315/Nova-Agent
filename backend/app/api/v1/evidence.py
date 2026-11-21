"""Claim-level evidence packs and environment comparability (M3).

A pack is built from the verification facts already stored on a repo, not
from a model's summary.  Every failure, skipped step and unsupported tool is
kept in ``unproven``.  Artifact paths must stay inside the repository root;
the API never reads arbitrary host paths.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.evidence import (
    Claim,
    EnvironmentManifest,
    EvidenceError,
    build_pack,
    compare_environments,
    list_packs,
    load_pack,
    save_pack,
    verify_pack,
)
from app.core.indexing.pipeline import get_repo
from app.core.security.auth import get_current_user
from app.db import query

router = APIRouter()


class EvidenceBuildIn(BaseModel):
    claims: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    artifact_paths: list[str] = Field(default_factory=list, max_length=50)
    environment: dict[str, Any] | None = None
    task_id: str = Field(default="", max_length=100)


class EvidenceCompareIn(BaseModel):
    local: dict[str, Any] = Field(default_factory=dict)
    container: dict[str, Any] = Field(default_factory=dict)


def _resolve_artifacts(root: Path, items: list[str]) -> list[Path]:
    base = root.resolve()
    resolved: list[Path] = []
    for raw in items:
        value = (raw or "").strip()
        if not value:
            continue
        candidate = (base / value).resolve()
        try:
            candidate.relative_to(base)
        except ValueError as exc:
            raise ValueError(f"工件路径必须位于仓库目录内：{raw}") from exc
        if not candidate.is_file():
            raise ValueError(f"工件不存在：{raw}")
        resolved.append(candidate)
    return resolved


@router.post("/evidence/repos/{repo_id}/packs")
async def build_evidence_pack(
    repo_id: str,
    body: EvidenceBuildIn | None = None,
    user: dict = Depends(get_current_user),
):
    repo = await get_repo(repo_id, user["id"])
    if not repo:
        raise HTTPException(status_code=404, detail="仓库不存在或无权访问")
    rows = await query("SELECT last_check FROM repos WHERE id = %s", (repo_id,))
    verification = rows[0][0] if rows else None
    if not isinstance(verification, dict) or not verification:
        raise HTTPException(
            status_code=409,
            detail="这个仓库还没有验证结果。先运行一次验证，再生成证据包。",
        )
    body = body or EvidenceBuildIn()
    try:
        artifacts = _resolve_artifacts(
            Path(str(repo.get("root_path") or "")), body.artifact_paths,
        )
        claims: list[Claim] = []
        for item in body.claims:
            try:
                claims.append(Claim.from_dict(item))
            except EvidenceError as exc:
                raise ValueError(f"主张格式不正确：{exc}") from exc
        environment = None
        if body.environment is not None:
            environment = EnvironmentManifest.from_dict(body.environment)
        pack = build_pack(
            verification=verification,
            repo=repo,
            claims=claims,
            artifact_paths=artifacts or None,
            environment=environment,
            task_id=body.task_id,
        )
        save_pack(pack, user["id"])
    except EvidenceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return pack.to_dict()


@router.get("/evidence/packs")
async def list_evidence_packs(user: dict = Depends(get_current_user)):
    return {"packs": list_packs(user["id"])}


@router.get("/evidence/packs/{pack_id}")
async def get_evidence_pack(
    pack_id: str,
    user: dict = Depends(get_current_user),
):
    try:
        pack = load_pack(user["id"], pack_id)
    except EvidenceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return pack.to_dict()


@router.post("/evidence/packs/{pack_id}/verify")
async def verify_evidence_pack(
    pack_id: str,
    user: dict = Depends(get_current_user),
):
    try:
        pack = load_pack(user["id"], pack_id)
    except EvidenceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not pack.repo_id:
        raise HTTPException(status_code=400, detail="证据包没有绑定仓库，无法核对工件")
    repo = await get_repo(pack.repo_id, user["id"])
    if not repo:
        raise HTTPException(status_code=404, detail="证据包绑定的仓库不存在或无权访问")
    root = str(repo.get("root_path") or "")
    if not root or not Path(root).is_dir():
        raise HTTPException(status_code=409, detail="仓库目录不可用，无法核对工件")
    result = verify_pack(pack, [Path(root)])
    return {"pack_id": pack.pack_id, **result}


@router.post("/evidence/compare")
async def compare_evidence_environments(
    body: EvidenceCompareIn,
    user: dict = Depends(get_current_user),
):
    try:
        local = EnvironmentManifest.from_dict(body.local)
        container = EnvironmentManifest.from_dict(body.container)
    except EvidenceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return compare_environments(local, container)


__all__ = ["router"]

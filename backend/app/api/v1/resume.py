"""Resume mode: profile, fact base and one-version-per-job (M4).

The API only reorganizes facts the user supplied.  Facts with numbers but no
evidence are stored as ``needs_confirmation`` and cannot be selected for a
job version until the user confirms or removes the number.
"""
from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path
from typing import Literal, NoReturn
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from app.core.documents.convert import ConversionError, convert_document
from app.core.resume import store
from app.core.resume.models import ResumeError, ResumeNotFound
from app.core.security.auth import get_current_user

router = APIRouter()

STAR_QUESTIONS: dict[str, list[dict[str, str]]] = {
    "student": [
        {"key": "situation", "question": "这件事发生在什么课程、社团、竞赛或实习里？时间和你的角色是什么？"},
        {"key": "task", "question": "你具体负责哪一部分？当时要解决的问题是什么？"},
        {"key": "action", "question": "你做了哪些动作？用了什么工具、方法或协作方式？"},
        {"key": "result", "question": "结果是什么？有数字就写数字；没有数字就写可核对的变化。"},
        {"key": "evidence", "question": "这个结果有什么材料能证明？例如仓库、证书、作品链接、老师评价。"},
    ],
    "tech": [
        {"key": "context", "question": "项目或系统的背景是什么？用户量、数据量或约束条件有哪些？"},
        {"key": "task", "question": "你负责的模块、接口或故障是什么？验收标准是什么？"},
        {"key": "action", "question": "你改了哪些关键代码或设计？为什么选这个方案？"},
        {"key": "result", "question": "结果如何验证？测试、监控、延迟、错误率或成本有什么变化？"},
        {"key": "evidence", "question": "证据在哪里？commit、PR、测试报告、监控截图或文档链接。"},
    ],
}


class ProfileIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    headline: str = Field(default="", max_length=200)
    contact: dict[str, str] = Field(default_factory=dict)


class FactIn(BaseModel):
    category: str = Field(min_length=1, max_length=60)
    title: str = Field(min_length=1, max_length=200)
    detail: str = Field(default="", max_length=4000)
    status: str = Field(default="self_reported", max_length=30)
    evidence: str = Field(default="", max_length=1000)
    metrics: list[str] = Field(default_factory=list, max_length=20)


class FactPatch(BaseModel):
    category: str | None = Field(default=None, max_length=60)
    title: str | None = Field(default=None, max_length=200)
    detail: str | None = Field(default=None, max_length=4000)
    status: str | None = Field(default=None, max_length=30)
    evidence: str | None = Field(default=None, max_length=1000)
    metrics: list[str] | None = Field(default=None, max_length=20)


class JobVersionIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    company: str = Field(default="", max_length=200)
    jd_text: str = Field(default="", max_length=20000)
    fact_ids: list[str] = Field(min_length=1, max_length=100)
    template: Literal["classic", "modern", "compact"] = "classic"
    notes: str = Field(default="", max_length=2000)


def _raise(exc: Exception) -> NoReturn:
    if isinstance(exc, ResumeNotFound):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, ResumeError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    raise exc


@router.get("/resume/questions")
async def resume_questions(
    audience: str = Query(default="student", pattern="^(student|tech)$"),
    user: dict = Depends(get_current_user),
):
    return {"audience": audience, "questions": STAR_QUESTIONS[audience]}


@router.post("/resume/profiles")
async def create_profile(body: ProfileIn, user: dict = Depends(get_current_user)):
    try:
        profile = store.create_profile(
            user["id"], name=body.name, headline=body.headline, contact=body.contact,
        )
    except Exception as exc:  # noqa: BLE001
        _raise(exc)
    return profile.to_dict()


@router.get("/resume/profiles")
async def list_profiles(user: dict = Depends(get_current_user)):
    return {"profiles": [profile.to_dict() for profile in store.list_profiles(user["id"])]}


@router.get("/resume/profiles/{profile_id}")
async def get_profile(profile_id: str, user: dict = Depends(get_current_user)):
    try:
        profile = store.get_profile(user["id"], profile_id)
        facts = store.list_facts(user["id"], profile_id)
        versions = store.list_job_versions(user["id"], profile_id)
    except Exception as exc:  # noqa: BLE001
        _raise(exc)
    return {
        "profile": profile.to_dict(),
        "facts": [fact.to_dict() for fact in facts],
        "versions": [version.to_dict() for version in versions],
    }


@router.get("/resume/profiles/{profile_id}/facts")
async def list_facts(profile_id: str, user: dict = Depends(get_current_user)):
    try:
        facts = store.list_facts(user["id"], profile_id)
    except Exception as exc:  # noqa: BLE001
        _raise(exc)
    return {"facts": [fact.to_dict() for fact in facts]}


@router.post("/resume/profiles/{profile_id}/facts")
async def add_fact(
    profile_id: str,
    body: FactIn,
    user: dict = Depends(get_current_user),
):
    try:
        fact = store.add_fact(
            user["id"], profile_id,
            category=body.category, title=body.title, detail=body.detail,
            status=body.status, evidence=body.evidence, metrics=body.metrics,
        )
    except Exception as exc:  # noqa: BLE001
        _raise(exc)
    return fact.to_dict()


@router.patch("/resume/profiles/{profile_id}/facts/{fact_id}")
async def update_fact(
    profile_id: str,
    fact_id: str,
    body: FactPatch,
    user: dict = Depends(get_current_user),
):
    try:
        fact = store.update_fact(
            user["id"], profile_id, fact_id,
            category=body.category, title=body.title, detail=body.detail,
            status=body.status, evidence=body.evidence, metrics=body.metrics,
        )
    except Exception as exc:  # noqa: BLE001
        _raise(exc)
    return fact.to_dict()


@router.post("/resume/profiles/{profile_id}/versions")
async def create_version(
    profile_id: str,
    body: JobVersionIn,
    user: dict = Depends(get_current_user),
):
    try:
        version = store.create_job_version(
            user["id"], profile_id,
            title=body.title, company=body.company, jd_text=body.jd_text,
            fact_ids=body.fact_ids, template=body.template, notes=body.notes,
        )
        markdown = store.render_job_version(user["id"], version.id)
    except Exception as exc:  # noqa: BLE001
        _raise(exc)
    return {**version.to_dict(), "markdown": markdown}


@router.get("/resume/profiles/{profile_id}/versions")
async def list_versions(profile_id: str, user: dict = Depends(get_current_user)):
    try:
        versions = store.list_job_versions(user["id"], profile_id)
    except Exception as exc:  # noqa: BLE001
        _raise(exc)
    return {"versions": [version.to_dict() for version in versions]}


@router.get("/resume/versions/{version_id}")
async def get_version(version_id: str, user: dict = Depends(get_current_user)):
    try:
        version = store.get_job_version(user["id"], version_id)
        markdown = store.render_job_version(user["id"], version_id)
    except Exception as exc:  # noqa: BLE001
        _raise(exc)
    return {**version.to_dict(), "markdown": markdown}


@router.get("/resume/versions/{version_id}/markdown")
async def download_version_markdown(
    version_id: str,
    user: dict = Depends(get_current_user),
):
    try:
        version = store.get_job_version(user["id"], version_id)
        markdown = store.render_job_version(user["id"], version_id)
    except Exception as exc:  # noqa: BLE001
        _raise(exc)
    filename = f"{version.title or 'resume'}.md".replace("/", "-")
    return PlainTextResponse(
        markdown,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


@router.post("/resume/versions/{version_id}/export")
async def export_version(
    version_id: str,
    fmt: str = Query(default="docx", alias="format", pattern="^(docx|pdf)$"),
    user: dict = Depends(get_current_user),
):
    """Convert the rendered Markdown to DOCX/PDF.

    Missing external tools return 409 with the tool diagnostics; the API never
    invents a PDF or silently uploads the document to a remote converter.
    """
    try:
        version = store.get_job_version(user["id"], version_id)
        markdown = store.render_job_version(user["id"], version_id)
    except Exception as exc:  # noqa: BLE001
        _raise(exc)
    workdir = Path(tempfile.mkdtemp(prefix="nova-resume-"))
    source = workdir / "resume.md"
    source.write_text(markdown, encoding="utf-8")
    try:
        result = await asyncio.to_thread(
            convert_document,
            source, fmt, workdir / "out", profile="resume", overwrite=True,
        )
    except ConversionError as exc:
        shutil.rmtree(workdir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result.status != "done" or not result.output_path:
        shutil.rmtree(workdir, ignore_errors=True)
        raise HTTPException(
            status_code=409,
            detail={
                "message": "导出工具不可用，文件没有生成。" + "；".join(result.diagnostics[:3]),
                "diagnostics": result.diagnostics,
                "fidelity": result.fidelity,
            },
        )
    filename = f"{version.title or 'resume'}.{fmt}".replace("/", "-")
    return FileResponse(
        result.output_path,
        filename=filename,
        media_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            if fmt == "docx" else "application/pdf"
        ),
        background=BackgroundTask(lambda: shutil.rmtree(workdir, ignore_errors=True)),
    )


__all__ = ["router"]

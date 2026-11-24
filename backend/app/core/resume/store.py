"""Per-user JSON storage for profiles, facts and tailored job versions.

Layout (under ``settings.user_data_dir``)::

    <user_id>/resume/
        profiles.json
        facts.json
        versions.json
        versions/<version_id>.md

Every registry is rewritten atomically (temp file + ``fsync`` + ``os.replace``)
under one module lock.  Reads and writes are scoped to the requested user's
directory, ids are validated before they are used in a path, and no request can
escape that directory.  The rendered Markdown only contains profile fields and
the facts the caller selected for that version.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import settings
from app.core.resume.models import (
    DEFAULT_TEMPLATE,
    MAX_JD_CHARS,
    TEMPLATES,
    Fact,
    JobVersion,
    Profile,
    ResumeError,
    ResumeNotFound,
    ensure_fact_includable,
    is_valid_resume_id,
    require_known_status,
)

PROFILE_SCHEMA = "resume-profiles-1.0"
FACT_SCHEMA = "resume-facts-1.0"
VERSION_SCHEMA = "resume-versions-1.0"
DISCLAIMER = "> 本文档仅根据你提供的事实生成；未编造指标、日期或公司信息。"
_LOCK = threading.RLock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalise_user_id(user_id: object) -> int:
    if isinstance(user_id, bool):
        raise ResumeError("用户 ID 不合法")
    if isinstance(user_id, int):
        value = user_id
    elif isinstance(user_id, str) and user_id.isascii() and user_id.isdigit():
        value = int(user_id)
    else:
        raise ResumeError("用户 ID 不合法")
    if value < 0:
        raise ResumeError("用户 ID 不合法")
    return value


def resume_root(user_id: int) -> Path:
    """Directory holding one user's resume data; never shared across users."""
    return Path(settings.user_data_dir) / str(_normalise_user_id(user_id)) / "resume"


def _profiles_path(root: Path) -> Path:
    return root / "profiles.json"


def _facts_path(root: Path) -> Path:
    return root / "facts.json"


def _versions_path(root: Path) -> Path:
    return root / "versions.json"


def _versions_dir(root: Path) -> Path:
    return root / "versions"


def _ensure_id(value: object, *, label: str = "简历数据") -> str:
    candidate = str(value or "").strip().lower()
    if not is_valid_resume_id(candidate):
        raise ResumeNotFound(f"{label}不存在")
    return candidate


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def _write_json(path: Path, payload: dict) -> None:
    _atomic_write(
        path,
        (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )


def _read_payload(path: Path, *, schema: str, key: str) -> dict:
    if not path.exists():
        return {"schema": schema, key: {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ResumeError(f"简历数据文件损坏：{path.name}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get(key), dict):
        raise ResumeError(f"简历数据文件格式不对：{path.name}")
    payload.setdefault("schema", schema)
    return payload


def _write_payload(path: Path, *, schema: str, key: str, items: dict[str, Any]) -> None:
    payload = {
        "schema": schema,
        key: {item_id: items[item_id].to_dict() for item_id in sorted(items)},
    }
    _write_json(path, payload)


def _load_profiles(root: Path) -> dict[str, Profile]:
    payload = _read_payload(_profiles_path(root), schema=PROFILE_SCHEMA, key="profiles")
    profiles: dict[str, Profile] = {}
    for item_id, raw in payload["profiles"].items():
        if not isinstance(raw, dict):
            raise ResumeError(f"简历档案数据损坏：{item_id}")
        profiles[str(item_id)] = Profile.from_dict({**raw, "id": str(item_id)})
    return profiles


def _save_profiles(root: Path, profiles: dict[str, Profile]) -> None:
    _write_payload(_profiles_path(root), schema=PROFILE_SCHEMA, key="profiles",
                   items=profiles)


def _load_facts(root: Path) -> dict[str, Fact]:
    payload = _read_payload(_facts_path(root), schema=FACT_SCHEMA, key="facts")
    facts: dict[str, Fact] = {}
    for item_id, raw in payload["facts"].items():
        if not isinstance(raw, dict):
            raise ResumeError(f"事实数据损坏：{item_id}")
        facts[str(item_id)] = Fact.from_dict({**raw, "id": str(item_id)})
    return facts


def _save_facts(root: Path, facts: dict[str, Fact]) -> None:
    _write_payload(_facts_path(root), schema=FACT_SCHEMA, key="facts", items=facts)


def _load_versions(root: Path) -> dict[str, JobVersion]:
    payload = _read_payload(_versions_path(root), schema=VERSION_SCHEMA, key="versions")
    versions: dict[str, JobVersion] = {}
    for item_id, raw in payload["versions"].items():
        if not isinstance(raw, dict):
            raise ResumeError(f"简历版本数据损坏：{item_id}")
        versions[str(item_id)] = JobVersion.from_dict({**raw, "id": str(item_id)})
    return versions


def _save_versions(root: Path, versions: dict[str, JobVersion]) -> None:
    _write_payload(_versions_path(root), schema=VERSION_SCHEMA, key="versions",
                   items=versions)


def _version_markdown_path(root: Path, version_id: str) -> Path:
    vid = _ensure_id(version_id, label="简历版本")
    versions_dir = _versions_dir(root).resolve()
    target = (versions_dir / f"{vid}.md").resolve()
    try:
        target.relative_to(versions_dir)
    except ValueError as exc:  # defensive; the id regex already forbids separators
        raise ResumeError("简历版本路径不合法") from exc
    return target


def _selected_ids(value: object) -> list[str]:
    if isinstance(value, str):
        items: list[object] = [value]
    elif isinstance(value, (list, tuple, set, frozenset)):
        items = sorted(value, key=str) if isinstance(value, (set, frozenset)) else list(value)
    else:
        raise ResumeError("事实列表格式不对")
    selected: list[str] = []
    for item in items:
        fact_id = _ensure_id(item, label="事实")
        if fact_id not in selected:
            selected.append(fact_id)
    return selected


def create_profile(user_id: int, *, name: str, headline: str = "",
                   contact: dict | None = None) -> Profile:
    """Create an empty profile; facts are added separately."""
    root = resume_root(user_id)
    if not str(name or "").strip():
        raise ResumeError("姓名不能为空")
    profile = Profile(
        id=uuid.uuid4().hex,
        user_id=_normalise_user_id(user_id),
        name=name,
        headline=headline,
        contact=contact or {},
    )
    with _LOCK:
        profiles = _load_profiles(root)
        while profile.id in profiles:  # uuid4 collision is theoretical; stay strict
            profile.id = uuid.uuid4().hex
        profiles[profile.id] = profile
        _save_profiles(root, profiles)
    return profile


def list_profiles(user_id: int) -> list[Profile]:
    root = resume_root(user_id)
    with _LOCK:
        profiles = _load_profiles(root)
    return sorted(
        profiles.values(),
        key=lambda profile: (profile.updated_at, profile.created_at, profile.id),
        reverse=True,
    )


def get_profile(user_id: int, profile_id: str) -> Profile:
    root = resume_root(user_id)
    pid = _ensure_id(profile_id, label="简历档案")
    with _LOCK:
        profile = _load_profiles(root).get(pid)
    if profile is None:
        raise ResumeNotFound("简历档案不存在")
    return profile


def add_fact(user_id: int, profile_id: str, *, category: str, title: str,
             detail: str = "", status: str = "self_reported", evidence: str = "",
             metrics: list[str] | str | None = None) -> Fact:
    """Add one fact.  Numeric metrics without evidence become needs_confirmation."""
    root = resume_root(user_id)
    pid = _ensure_id(profile_id, label="简历档案")
    clean_status = require_known_status(status)
    if not str(category or "").strip():
        raise ResumeError("事实分类不能为空")
    if not str(title or "").strip():
        raise ResumeError("事实标题不能为空")
    with _LOCK:
        if pid not in _load_profiles(root):
            raise ResumeNotFound("简历档案不存在")
        facts = _load_facts(root)
        fact = Fact(
            id=uuid.uuid4().hex,
            profile_id=pid,
            category=category,
            title=title,
            detail=detail,
            status=clean_status,
            evidence=evidence,
            metrics=metrics,
        )
        while fact.id in facts:
            fact.id = uuid.uuid4().hex
        facts[fact.id] = fact
        _save_facts(root, facts)
    return fact


def update_fact(user_id: int, profile_id: str, fact_id: str, *,
                category: str | None = None, title: str | None = None,
                detail: str | None = None, status: str | None = None,
                evidence: str | None = None,
                metrics: list[str] | str | None = None) -> Fact:
    """Update selected fields; the evidence/status invariant is re-applied."""
    root = resume_root(user_id)
    pid = _ensure_id(profile_id, label="简历档案")
    fid = _ensure_id(fact_id, label="事实")
    clean_status = require_known_status(status) if status is not None else None
    if category is not None and not str(category).strip():
        raise ResumeError("事实分类不能为空")
    if title is not None and not str(title).strip():
        raise ResumeError("事实标题不能为空")
    with _LOCK:
        if pid not in _load_profiles(root):
            raise ResumeNotFound("简历档案不存在")
        facts = _load_facts(root)
        fact = facts.get(fid)
        if fact is None or fact.profile_id != pid:
            raise ResumeNotFound("事实不存在")
        changes: dict[str, Any] = {}
        if category is not None:
            changes["category"] = category
        if title is not None:
            changes["title"] = title
        if detail is not None:
            changes["detail"] = detail
        if clean_status is not None:
            changes["status"] = clean_status
        if evidence is not None:
            changes["evidence"] = evidence
        if metrics is not None:
            changes["metrics"] = metrics
        changes["updated_at"] = _now()
        updated = replace(fact, **changes)
        facts[fid] = updated
        _save_facts(root, facts)
    return updated


def list_facts(user_id: int, profile_id: str) -> list[Fact]:
    root = resume_root(user_id)
    pid = _ensure_id(profile_id, label="简历档案")
    with _LOCK:
        if pid not in _load_profiles(root):
            raise ResumeNotFound("简历档案不存在")
        facts = _load_facts(root)
    return sorted(
        (fact for fact in facts.values() if fact.profile_id == pid),
        key=lambda fact: (fact.category, fact.created_at, fact.id),
    )


def create_job_version(user_id: int, profile_id: str, *, title: str,
                       company: str = "", jd_text: str = "",
                       fact_ids: list[str] | tuple[str, ...] | str,
                       template: str = DEFAULT_TEMPLATE,
                       notes: str = "") -> JobVersion:
    """Snapshot the JD, validate the selected facts and write Markdown."""
    root = resume_root(user_id)
    pid = _ensure_id(profile_id, label="简历档案")
    if not str(title or "").strip():
        raise ResumeError("职位名称不能为空")
    template_value = str(template or DEFAULT_TEMPLATE).strip().lower()
    if template_value not in TEMPLATES:
        raise ResumeError(f"不支持的简历模板：{template}")
    snapshot = str(jd_text or "")
    if len(snapshot) > MAX_JD_CHARS:
        raise ResumeError(f"职位描述不能超过 {MAX_JD_CHARS} 字")
    ids = _selected_ids(fact_ids)
    if not ids:
        raise ResumeError("请至少选择一个事实")
    version = JobVersion(
        id=uuid.uuid4().hex,
        profile_id=pid,
        title=title,
        company=company,
        jd_text=snapshot,
        fact_ids=ids,
        template=template_value,
        notes=notes,
    )

    with _LOCK:
        profile = _load_profiles(root).get(pid)
        if profile is None:
            raise ResumeNotFound("简历档案不存在")
        stored = _load_facts(root)
        selected: list[Fact] = []
        for fact_id in ids:
            fact = stored.get(fact_id)
            if fact is None or fact.profile_id != pid:
                raise ResumeNotFound("事实不存在")
            ensure_fact_includable(fact)
            selected.append(fact)
        versions = _load_versions(root)
        while version.id in versions:
            version.id = uuid.uuid4().hex
        markdown = _render_markdown(profile, selected, version.template)
        markdown_path = _version_markdown_path(root, version.id)
        _atomic_write(markdown_path, markdown.encode("utf-8"))
        versions[version.id] = version
        try:
            _save_versions(root, versions)
        except BaseException:
            try:
                markdown_path.unlink()
            except OSError:
                pass
            raise
    return version


def list_job_versions(user_id: int, profile_id: str | None = None) -> list[JobVersion]:
    root = resume_root(user_id)
    pid: str | None = None
    with _LOCK:
        if profile_id is not None:
            pid = _ensure_id(profile_id, label="简历档案")
            if pid not in _load_profiles(root):
                raise ResumeNotFound("简历档案不存在")
        versions = _load_versions(root)
    return sorted(
        (
            version for version in versions.values()
            if pid is None or version.profile_id == pid
        ),
        key=lambda version: (version.created_at, version.id),
        reverse=True,
    )


def get_job_version(user_id: int, version_id: str) -> JobVersion:
    root = resume_root(user_id)
    vid = _ensure_id(version_id, label="简历版本")
    with _LOCK:
        version = _load_versions(root).get(vid)
    if version is None:
        raise ResumeNotFound("简历版本不存在")
    return version


def render_job_version(user_id: int, version_id: str) -> str:
    """Return the Markdown snapshot captured when the version was created.

    A job version is a snapshot: editing, excluding or downgrading a fact
    later must not change a resume the author already reviewed.  Versions
    created before snapshots were stored are rendered once from their selected
    facts and saved, so every later read stays stable.
    """
    root = resume_root(user_id)
    vid = _ensure_id(version_id, label="简历版本")
    with _LOCK:
        version = _load_versions(root).get(vid)
        if version is None:
            raise ResumeNotFound("简历版本不存在")
        markdown_path = _version_markdown_path(root, vid)
        if markdown_path.is_file():
            return markdown_path.read_text(encoding="utf-8")
        profile = _load_profiles(root).get(version.profile_id)
        if profile is None:
            raise ResumeNotFound("简历档案不存在")
        stored = _load_facts(root)
        selected: list[Fact] = []
        for fact_id in version.fact_ids:
            fact = stored.get(fact_id)
            if fact is None or fact.profile_id != version.profile_id:
                raise ResumeNotFound("事实不存在")
            ensure_fact_includable(fact)
            selected.append(fact)
        markdown = _render_markdown(profile, selected, version.template)
        _atomic_write(markdown_path, markdown.encode("utf-8"))
    return markdown


def _single_line(value: object, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _contact_line(contact: dict[str, str]) -> str:
    parts: list[str] = []
    for key, value in contact.items():
        label = _single_line(key, 40)
        text = _single_line(value, 300)
        if label and text:
            parts.append(f"{label}：{text}")
    return " | ".join(parts)


def _render_markdown(
    profile: Profile, facts: list[Fact], template: str = DEFAULT_TEMPLATE,
) -> str:
    """Render only profile fields and selected facts; never add new content.

    ``template`` changes heading depth and whether metrics/evidence sit on
    nested lines or stay inline.  It never adds, rewrites or reorders facts.
    """
    template = template if template in TEMPLATES else DEFAULT_TEMPLATE
    lines: list[str] = [f"# {profile.name}", ""]
    headline = _single_line(profile.headline, 200)
    if headline:
        lines.extend([f"**{headline}**" if template == "modern" else headline, ""])
    contact = _contact_line(profile.contact)
    if contact:
        lines.extend([contact, ""])
    lines.extend([DISCLAIMER, ""])

    grouped: dict[str, list[Fact]] = {}
    for fact in facts:
        grouped.setdefault(fact.category, []).append(fact)
    heading = "###" if template in ("modern", "compact") else "##"
    for category, items in grouped.items():
        lines.extend([f"{heading} {category}", ""])
        for fact in items:
            detail = _single_line(fact.detail, 4000)
            if template == "compact":
                extras: list[str] = []
                if fact.metrics:
                    extras.append("指标：" + "；".join(fact.metrics))
                if fact.evidence:
                    extras.append("依据：" + _single_line(fact.evidence, 1000))
                suffix = f"（{'；'.join(extras)}）" if extras else ""
                line = f"- **{fact.title}**" + (f"：{detail}" if detail else "")
                lines.append(line + suffix)
                continue
            if detail:
                lines.append(f"- **{fact.title}**：{detail}")
            else:
                lines.append(f"- **{fact.title}**")
            if fact.metrics:
                lines.append(f"  - 指标：{'；'.join(fact.metrics)}")
            if fact.evidence:
                lines.append(f"  - 依据：{_single_line(fact.evidence, 1000)}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "FACT_SCHEMA", "PROFILE_SCHEMA", "VERSION_SCHEMA", "add_fact",
    "create_job_version", "create_profile", "get_job_version", "get_profile",
    "list_facts", "list_job_versions", "list_profiles", "render_job_version",
    "resume_root", "update_fact",
]

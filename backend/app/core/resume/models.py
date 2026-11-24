"""Resume facts, profiles and tailored job versions.

The resume mode only reorganizes what the user has already stated.  Every fact
carries an explicit evidence status; a fact that still needs confirmation (or
was excluded) can never reach a job version.  A numeric claim without an
evidence note is downgraded to ``needs_confirmation`` instead of being shown
as if it were verified.

Nothing here touches the database or the network: :mod:`app.core.resume.store`
persists these dataclasses as per-user JSON.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

FACT_STATUSES = (
    "self_reported",
    "evidence_linked",
    "needs_confirmation",
    "excluded",
)
INCLUDABLE_FACT_STATUSES = ("self_reported", "evidence_linked")
STATUS_LABELS = {
    "self_reported": "本人陈述",
    "evidence_linked": "已关联依据",
    "needs_confirmation": "待确认",
    "excluded": "已排除",
}
TEMPLATES = ("classic", "modern", "compact")
DEFAULT_TEMPLATE = "classic"
RESUME_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")
MAX_JD_CHARS = 100_000
MAX_METRICS = 12
MAX_METRIC_CHARS = 200
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class ResumeError(ValueError):
    """A resume operation was refused or its input was not usable."""


class ResumeNotFound(ResumeError):
    """No profile, fact or job version exists for the requested id."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_text(value: object, limit: int) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL_RE.sub("", text)
    return text.strip()[:limit]


def _clean_block(value: object, limit: int) -> str:
    """Clean a block of text but preserve its exact surrounding whitespace."""
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    return _CONTROL_RE.sub("", text)[:limit]


def _one_line(value: object, limit: int) -> str:
    text = _CONTROL_RE.sub("", str(value or "").replace("\r", "\n"))
    return re.sub(r"\s+", " ", text).strip()[:limit]


def is_valid_resume_id(value: object) -> bool:
    return isinstance(value, str) and bool(RESUME_ID_PATTERN.match(value.strip().lower()))


def normalise_status(value: object, *, default: str = "needs_confirmation") -> str:
    """Repair an unknown status; an unknown value must never become includable."""
    status = str(value or "").strip().lower()
    return status if status in FACT_STATUSES else default


def require_known_status(value: object) -> str:
    """Validate a status supplied by a caller (no silent repair on writes)."""
    status = str(value or "").strip().lower()
    if status not in FACT_STATUSES:
        raise ResumeError(f"未知的事实状态：{value}")
    return status


def _pick(mapping: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        item = mapping.get(key)
        if isinstance(item, bool) or item is None:
            continue
        if isinstance(item, (int, float)):
            return str(item)
        if isinstance(item, str) and item.strip():
            return item.strip()
    return ""


def _metric_text(value: object) -> str:
    if isinstance(value, bool):
        return ""
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return _one_line(value, MAX_METRIC_CHARS)
    if isinstance(value, dict):
        label = _pick(value, ("label", "name", "text", "title"))
        amount = _pick(value, ("value", "amount", "number", "count"))
        unit = _pick(value, ("unit", "suffix"))
        if amount:
            text = f"{label} {amount}{unit}" if label else f"{amount}{unit}"
        else:
            text = label
        return _one_line(text, MAX_METRIC_CHARS)
    return ""


def normalise_metrics(value: object) -> list[str]:
    """Coerce user metric shapes into bounded one-line strings."""
    if value is None:
        return []
    if isinstance(value, (str, int, float)) and not isinstance(value, bool):
        items: list[object] = [value]
    elif isinstance(value, (list, tuple)):
        items = list(value)
    else:
        return []
    result: list[str] = []
    for item in items:
        text = _metric_text(item)
        if text and text not in result:
            result.append(text)
        if len(result) >= MAX_METRICS:
            break
    return result


def metric_has_number(metric: str) -> bool:
    return bool(re.search(r"\d", metric or ""))


def requires_evidence(metrics: list[str]) -> bool:
    return any(metric_has_number(metric) for metric in metrics)


def needs_confirmation(metrics: list[str], evidence: str) -> bool:
    """A numeric metric is only presentable with a non-empty evidence note."""
    return requires_evidence(metrics) and not (evidence or "").strip()


def normalise_contact(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    contact: dict[str, str] = {}
    for key, item in value.items():
        label = _one_line(key, 40)
        if not label:
            continue
        if isinstance(item, bool) or not isinstance(item, (str, int, float)):
            continue
        text = _one_line(item, 300)
        if text:
            contact[label] = text
    return contact


def normalise_fact_ids(value: object) -> list[str]:
    if isinstance(value, str):
        items: list[object] = [value]
    elif isinstance(value, (list, tuple)):
        items = list(value)
    elif isinstance(value, (set, frozenset)):
        items = sorted(value, key=str)
    else:
        return []
    result: list[str] = []
    for item in items:
        candidate = str(item or "").strip().lower()
        if is_valid_resume_id(candidate) and candidate not in result:
            result.append(candidate)
    return result


@dataclass
class Profile:
    id: str
    user_id: int
    name: str
    headline: str = ""
    contact: dict[str, str] = field(default_factory=dict)
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def __post_init__(self) -> None:
        self.id = str(self.id or "").strip().lower()
        try:
            self.user_id = int(self.user_id)
        except (TypeError, ValueError):
            self.user_id = 0
        self.name = _one_line(self.name, 120) or "未命名"
        self.headline = _one_line(self.headline, 200)
        self.contact = normalise_contact(self.contact)
        self.created_at = str(self.created_at or "") or _now()
        self.updated_at = str(self.updated_at or "") or self.created_at

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "name": self.name,
            "headline": self.headline,
            "contact": dict(self.contact),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Profile":
        if not isinstance(data, dict):
            raise ResumeError("简历档案数据格式不对")
        return cls(
            id=str(data.get("id") or ""),
            user_id=data.get("user_id") or 0,
            name=str(data.get("name") or ""),
            headline=str(data.get("headline") or ""),
            contact=data.get("contact") if isinstance(data.get("contact"), dict) else {},
            created_at=str(data.get("created_at") or ""),
            updated_at=str(data.get("updated_at") or ""),
        )


@dataclass
class Fact:
    id: str
    profile_id: str
    category: str
    title: str
    detail: str = ""
    status: str = "self_reported"
    evidence: str = ""
    metrics: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def __post_init__(self) -> None:
        self.id = str(self.id or "").strip().lower()
        self.profile_id = str(self.profile_id or "").strip().lower()
        self.category = _one_line(self.category, 60) or "未分类"
        self.title = _one_line(self.title, 200) or "未命名事实"
        self.detail = _clean_text(self.detail, 4000)
        self.status = normalise_status(self.status)
        self.evidence = _clean_text(self.evidence, 1000)
        self.metrics = normalise_metrics(self.metrics)
        self.created_at = str(self.created_at or "") or _now()
        self.updated_at = str(self.updated_at or "") or self.created_at
        # Safety invariant: a numeric claim without an evidence note is never
        # allowed to look verified, even if it was stored that way before.
        if self.status in INCLUDABLE_FACT_STATUSES and needs_confirmation(
            self.metrics, self.evidence,
        ):
            self.status = "needs_confirmation"

    @property
    def includable(self) -> bool:
        return (
            self.status in INCLUDABLE_FACT_STATUSES
            and not needs_confirmation(self.metrics, self.evidence)
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "profile_id": self.profile_id,
            "category": self.category,
            "title": self.title,
            "detail": self.detail,
            "status": self.status,
            "evidence": self.evidence,
            "metrics": list(self.metrics),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Fact":
        if not isinstance(data, dict):
            raise ResumeError("事实数据格式不对")
        return cls(
            id=str(data.get("id") or ""),
            profile_id=str(data.get("profile_id") or ""),
            category=str(data.get("category") or ""),
            title=str(data.get("title") or ""),
            detail=str(data.get("detail") or ""),
            status=str(data.get("status") or ""),
            evidence=str(data.get("evidence") or ""),
            metrics=data.get("metrics"),
            created_at=str(data.get("created_at") or ""),
            updated_at=str(data.get("updated_at") or ""),
        )


@dataclass
class JobVersion:
    id: str
    profile_id: str
    title: str
    company: str = ""
    jd_text: str = ""
    jd_sha256: str = ""
    fact_ids: list[str] = field(default_factory=list)
    template: str = DEFAULT_TEMPLATE
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    notes: str = ""

    def __post_init__(self) -> None:
        self.id = str(self.id or "").strip().lower()
        self.profile_id = str(self.profile_id or "").strip().lower()
        self.title = _one_line(self.title, 200)
        self.company = _one_line(self.company, 200)
        self.jd_text = _clean_block(self.jd_text, MAX_JD_CHARS)
        self.fact_ids = normalise_fact_ids(self.fact_ids)
        template = str(self.template or "").strip().lower()
        self.template = template if template in TEMPLATES else DEFAULT_TEMPLATE
        self.notes = _clean_text(self.notes, 2000)
        self.created_at = str(self.created_at or "") or _now()
        self.updated_at = str(self.updated_at or "") or self.created_at
        # Recompute rather than trust a stale/hand-edited hash: the stored hash
        # must always describe the stored JD snapshot.
        self.jd_sha256 = hashlib.sha256(self.jd_text.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "profile_id": self.profile_id,
            "title": self.title,
            "company": self.company,
            "jd_text": self.jd_text,
            "jd_sha256": self.jd_sha256,
            "fact_ids": list(self.fact_ids),
            "template": self.template,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "JobVersion":
        if not isinstance(data, dict):
            raise ResumeError("简历版本数据格式不对")
        return cls(
            id=str(data.get("id") or ""),
            profile_id=str(data.get("profile_id") or ""),
            title=str(data.get("title") or ""),
            company=str(data.get("company") or ""),
            jd_text=str(data.get("jd_text") or ""),
            jd_sha256=str(data.get("jd_sha256") or ""),
            fact_ids=data.get("fact_ids"),
            template=str(data.get("template") or ""),
            created_at=str(data.get("created_at") or ""),
            updated_at=str(data.get("updated_at") or ""),
            notes=str(data.get("notes") or ""),
        )


def ensure_fact_includable(fact: Fact) -> None:
    """Refuse a fact that may not appear in a job version."""
    if fact.status not in FACT_STATUSES:
        raise ResumeError(f"事实「{fact.title}」的状态不合法，不能加入简历版本")
    if fact.status not in INCLUDABLE_FACT_STATUSES:
        label = STATUS_LABELS.get(fact.status, fact.status)
        raise ResumeError(
            f"事实「{fact.title}」当前状态为「{label}」（{fact.status}），"
            "不能加入简历版本；只有「本人陈述」（self_reported）或"
            "「已关联依据」（evidence_linked）的事实可以加入。"
        )
    if needs_confirmation(fact.metrics, fact.evidence):
        raise ResumeError(
            f"事实「{fact.title}」包含数字指标但缺少依据，不能加入简历版本；"
            "请补充依据或先确认。"
        )


__all__ = [
    "DEFAULT_TEMPLATE", "FACT_STATUSES", "INCLUDABLE_FACT_STATUSES",
    "MAX_JD_CHARS", "RESUME_ID_PATTERN", "STATUS_LABELS", "TEMPLATES",
    "Fact", "JobVersion", "Profile", "ResumeError", "ResumeNotFound",
    "ensure_fact_includable", "is_valid_resume_id", "metric_has_number",
    "needs_confirmation", "normalise_contact", "normalise_fact_ids",
    "normalise_metrics", "normalise_status", "require_known_status",
    "requires_evidence",
]

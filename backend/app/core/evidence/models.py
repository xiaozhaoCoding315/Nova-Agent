"""Claim-level evidence packs.

An evidence pack records what was actually checked, in a form that can be
saved, loaded and re-verified offline.  Every claim carries an explicit kind
and status: a failed, skipped or unsupported step is never upgraded into a
confirmation, and anything that was not proven stays in ``unproven``.

The canonical JSON form (sorted keys, no whitespace, UTF-8) is the input to
``manifest_sha256``, so the same pack always hashes to the same value.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

SCHEMA_VERSION = "evidence-pack-1.0"
CLAIM_KINDS = ("code_fact", "test_result", "human_note", "unverified")
CLAIM_STATUSES = ("confirmed", "failed", "not_run", "unsupported", "unverified")


class EvidenceError(Exception):
    """An evidence pack could not be built, stored or read."""


def canonical_json(value: Any) -> str:
    """Stable JSON text: sorted keys, compact separators, UTF-8 safe."""
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        default=str,
    )


def canonical_bytes(value: Any) -> bytes:
    return canonical_json(value).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_claim_kind(value: Any) -> str:
    """Unknown kinds become ``unverified`` instead of being guessed."""
    kind = str(value or "").strip().lower()
    return kind if kind in CLAIM_KINDS else "unverified"


def normalize_claim_status(value: Any) -> str:
    """Unknown statuses become ``unverified``, never ``confirmed``."""
    status = str(value or "").strip().lower()
    return status if status in CLAIM_STATUSES else "unverified"


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def _text_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return ["" if item is None else str(item) for item in value]


def _line_number(value: Any) -> int | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@dataclass
class Claim:
    """One statement backed by evidence (or explicitly left unverified)."""

    claim_id: str
    statement: str
    kind: str = "unverified"
    status: str = "unverified"
    commit: str = ""
    path: str = ""
    line: int | None = None
    evidence_ids: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.claim_id = _text(self.claim_id)
        self.statement = _text(self.statement)
        self.commit = _text(self.commit)
        self.path = _text(self.path)
        self.line = _line_number(self.line)
        self.evidence_ids = _text_list(self.evidence_ids)
        self.notes = _text_list(self.notes)

        raw_kind = str(self.kind or "").strip().lower()
        if raw_kind and raw_kind not in CLAIM_KINDS:
            self.notes.append(f"未知类型已按 unverified 处理：{raw_kind}")
        self.kind = normalize_claim_kind(raw_kind)

        raw_status = str(self.status or "").strip().lower()
        if raw_status and raw_status not in CLAIM_STATUSES:
            self.notes.append(f"未知状态已按 unverified 处理：{raw_status}")
        self.status = normalize_claim_status(raw_status)

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "statement": self.statement,
            "kind": self.kind,
            "status": self.status,
            "commit": self.commit,
            "path": self.path,
            "line": self.line,
            "evidence_ids": list(self.evidence_ids),
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: Any) -> "Claim":
        if not isinstance(data, dict):
            raise EvidenceError("claim 格式不正确：应为 JSON 对象")
        return cls(
            claim_id=_text(data.get("claim_id")),
            statement=_text(data.get("statement")),
            kind=data.get("kind"),
            status=data.get("status"),
            commit=_text(data.get("commit")),
            path=_text(data.get("path")),
            line=data.get("line"),
            evidence_ids=_text_list(data.get("evidence_ids")),
            notes=_text_list(data.get("notes")),
        )


@dataclass(frozen=True)
class EvidenceArtifact:
    """A file that backs one or more claims, identified by its content hash."""

    artifact_id: str
    name: str
    sha256: str
    size: int
    media_type: str = "application/octet-stream"
    created_at: str = ""

    def manifest_row(self) -> dict[str, Any]:
        """The hash row included in the pack-level manifest."""
        return {
            "artifact_id": self.artifact_id,
            "name": self.name,
            "sha256": self.sha256,
            "size": self.size,
            "media_type": self.media_type,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "name": self.name,
            "sha256": self.sha256,
            "size": self.size,
            "media_type": self.media_type,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Any) -> "EvidenceArtifact":
        if not isinstance(data, dict):
            raise EvidenceError("artifact 格式不正确：应为 JSON 对象")
        try:
            size = int(data.get("size") or 0)
        except (TypeError, ValueError):
            size = 0
        return cls(
            artifact_id=_text(data.get("artifact_id")),
            name=_text(data.get("name")),
            sha256=_normalise_sha256(data.get("sha256")),
            size=size,
            media_type=_text(data.get("media_type")) or "application/octet-stream",
            created_at=_text(data.get("created_at")),
        )


def _normalise_sha256(value: Any) -> str:
    text = _text(value).strip().lower()
    if text.startswith("sha256:"):
        text = text[7:]
    return text


@dataclass
class EnvironmentManifest:
    """Where the work ran.  Empty values mean "not recorded", not "same"."""

    mode: str = "unknown"                 # container | host | unknown
    os: str = ""
    arch: str = ""
    isolation: str = "unknown"            # container | none | unknown
    network: str = "unknown"              # disabled | enabled | host | unknown
    image_digest: str = ""
    tool_versions: dict[str, str] = field(default_factory=dict)
    working_dir: str = ""
    notes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.mode = _text(self.mode) or "unknown"
        self.os = _text(self.os)
        self.arch = _text(self.arch)
        self.isolation = _text(self.isolation) or "unknown"
        self.network = _text(self.network) or "unknown"
        self.image_digest = _text(self.image_digest)
        self.working_dir = _text(self.working_dir)
        self.notes = _text_list(self.notes)
        versions = self.tool_versions if isinstance(self.tool_versions, dict) else {}
        self.tool_versions = {
            _text(key): _text(value)
            for key, value in versions.items()
            if _text(key).strip()
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "os": self.os,
            "arch": self.arch,
            "isolation": self.isolation,
            "network": self.network,
            "image_digest": self.image_digest,
            "tool_versions": dict(self.tool_versions),
            "working_dir": self.working_dir,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: Any) -> "EnvironmentManifest":
        if isinstance(data, EnvironmentManifest):
            return data
        if data is None:
            return cls()
        if not isinstance(data, dict):
            raise EvidenceError("environment 格式不正确：应为 JSON 对象")
        versions = data.get("tool_versions")
        raw_notes = data.get("notes")
        notes = (
            [_text(item) for item in raw_notes]
            if isinstance(raw_notes, (list, tuple)) else []
        )
        return cls(
            mode=_text(data.get("mode")) or "unknown",
            os=_text(data.get("os")),
            arch=_text(data.get("arch")),
            isolation=_text(data.get("isolation")) or "unknown",
            network=_text(data.get("network")) or "unknown",
            image_digest=_text(data.get("image_digest")),
            tool_versions=versions if isinstance(versions, dict) else {},
            working_dir=_text(data.get("working_dir")),
            notes=notes,
        )


@dataclass
class EvidencePack:
    """A saved bundle of claims, artifacts and the environment they describe."""

    pack_id: str
    task_id: str = ""
    repo_id: str = ""
    commit: str = ""
    created_at: str = ""
    claims: list[Claim] = field(default_factory=list)
    artifacts: list[EvidenceArtifact] = field(default_factory=list)
    environment: EnvironmentManifest = field(default_factory=EnvironmentManifest)
    unproven: list[str] = field(default_factory=list)
    manifest_sha256: str = ""

    def __post_init__(self) -> None:
        self.pack_id = _text(self.pack_id)
        self.task_id = _text(self.task_id)
        self.repo_id = _text(self.repo_id)
        self.commit = _text(self.commit)
        self.created_at = _text(self.created_at) or now_iso()
        self.claims = [
            item if isinstance(item, Claim) else Claim.from_dict(item)
            for item in (self.claims or [])
        ]
        self.artifacts = [
            item if isinstance(item, EvidenceArtifact) else EvidenceArtifact.from_dict(item)
            for item in (self.artifacts or [])
        ]
        if not isinstance(self.environment, EnvironmentManifest):
            self.environment = EnvironmentManifest.from_dict(self.environment)
        if not isinstance(self.unproven, (list, tuple)):
            raise EvidenceError("证据包格式不正确：unproven 必须为字符串列表")
        # Explicit conversion, never filtering: an unproven item must not
        # disappear just because it is empty or not a plain string.
        self.unproven = ["" if item is None else str(item) for item in self.unproven]
        self.manifest_sha256 = _text(self.manifest_sha256)

    def manifest(self) -> dict[str, Any]:
        """Everything the manifest hash covers, with deterministic ordering."""
        claims = sorted(
            (claim.to_dict() for claim in self.claims),
            key=lambda row: (row["claim_id"], row["statement"]),
        )
        artifacts = sorted(
            (artifact.manifest_row() for artifact in self.artifacts),
            key=lambda row: (row["name"], row["artifact_id"], row["sha256"]),
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "pack_id": self.pack_id,
            "task_id": self.task_id,
            "repo_id": self.repo_id,
            "commit": self.commit,
            "created_at": self.created_at,
            "claims": claims,
            "artifacts": artifacts,
            "environment": self.environment.to_dict(),
            "unproven": list(self.unproven),
        }

    def compute_manifest_sha256(self) -> str:
        return canonical_sha256(self.manifest())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "pack_id": self.pack_id,
            "task_id": self.task_id,
            "repo_id": self.repo_id,
            "commit": self.commit,
            "created_at": self.created_at,
            "claims": [claim.to_dict() for claim in self.claims],
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "environment": self.environment.to_dict(),
            "unproven": list(self.unproven),
            "manifest_sha256": self.manifest_sha256,
        }

    @classmethod
    def from_dict(cls, data: Any) -> "EvidencePack":
        if not isinstance(data, dict):
            raise EvidenceError("证据包格式不正确：应为 JSON 对象")
        schema = _text(data.get("schema_version"))
        if schema and not schema.startswith("evidence-pack-"):
            raise EvidenceError(f"证据包版本不支持：{schema}")

        raw_claims = data.get("claims", [])
        if raw_claims is None:
            raw_claims = []
        if not isinstance(raw_claims, list):
            raise EvidenceError("证据包格式不正确：claims 应为列表")

        raw_artifacts = data.get("artifacts", [])
        if raw_artifacts is None:
            raw_artifacts = []
        if not isinstance(raw_artifacts, list):
            raise EvidenceError("证据包格式不正确：artifacts 应为列表")

        raw_unproven = data.get("unproven", [])
        if not isinstance(raw_unproven, list):
            raise EvidenceError("证据包格式不正确：unproven 应为字符串列表")

        raw_environment = data.get("environment")
        return cls(
            pack_id=_text(data.get("pack_id")),
            task_id=_text(data.get("task_id")),
            repo_id=_text(data.get("repo_id")),
            commit=_text(data.get("commit")),
            created_at=_text(data.get("created_at")),
            claims=[Claim.from_dict(item) for item in raw_claims],
            artifacts=[EvidenceArtifact.from_dict(item) for item in raw_artifacts],
            environment=EnvironmentManifest.from_dict(raw_environment),
            unproven=["" if item is None else str(item) for item in raw_unproven],
            manifest_sha256=_text(data.get("manifest_sha256")),
        )


__all__ = [
    "CLAIM_KINDS", "CLAIM_STATUSES", "SCHEMA_VERSION", "Claim",
    "EnvironmentManifest", "EvidenceArtifact", "EvidenceError", "EvidencePack",
    "canonical_bytes", "canonical_json", "canonical_sha256", "normalize_claim_kind",
    "normalize_claim_status", "now_iso",
]

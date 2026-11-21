"""Build, store and re-verify claim-level evidence packs.

A pack is built from the verification facts produced by
``app.core.verify``.  Passed steps become confirmed test claims; failed,
skipped, not-run and unsupported steps keep their meaning and are listed in
``unproven``.  Artifact hashes are recorded in a sorted manifest so the same
inputs always produce the same ``manifest_sha256``.

Storage is per user: ``settings.user_data_dir/<user_id>/evidence/<pack_id>.json``.
Writes are atomic.  Text fields are redacted before they are saved, so a token
printed by a failing test cannot end up in the pack.
"""
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import tempfile
import uuid
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Sequence

from app.config import settings
from app.core.evidence.models import (
    Claim,
    EnvironmentManifest,
    EvidenceArtifact,
    EvidenceError,
    EvidencePack,
    canonical_sha256,
    now_iso,
)
from app.core.security.redaction import redact_text

_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_DIGEST_PATTERN = re.compile(
    r"(?:^|@)sha256:[0-9a-fA-F]{64}$|^[0-9a-fA-F]{64}$"
)
# The shared helper catches keys at line start; these two also catch inline
# assignments and bearer headers inside one-line statements/reasons.
_INLINE_ASSIGNMENT = re.compile(
    r"(?i)\b([A-Z0-9_]*(?:API[_-]?KEY|TOKEN|SECRET|PASSWORD|PASSWD)[A-Z0-9_]*)"
    r"\s*[=:]\s*([^\s,;，；]+)"
)
_BEARER = re.compile(r"(?i)\b(Bearer)\s+([A-Za-z0-9._~+/=-]{16,})")


def _redact(value: str) -> str:
    text = redact_text(value)
    text = _INLINE_ASSIGNMENT.sub(
        lambda match: f"{match.group(1)}=[REDACTED]", text,
    )
    return _BEARER.sub("Bearer [REDACTED]", text)


def _redact_environment(environment: EnvironmentManifest) -> None:
    environment.mode = _redact(environment.mode)
    environment.os = _redact(environment.os)
    environment.arch = _redact(environment.arch)
    environment.isolation = _redact(environment.isolation)
    environment.network = _redact(environment.network)
    environment.image_digest = _redact(environment.image_digest)
    environment.working_dir = _redact(environment.working_dir)
    environment.tool_versions = {
        _redact(key): _redact(value)
        for key, value in environment.tool_versions.items()
    }
    environment.notes = [_redact(note) for note in environment.notes]


def redact_pack(pack: EvidencePack) -> EvidencePack:
    """Redact claim text and environment metadata in place."""
    for claim in pack.claims:
        claim.statement = _redact(claim.statement)
        claim.path = _redact(claim.path)
        claim.notes = [_redact(note) for note in claim.notes]
    _redact_environment(pack.environment)
    pack.unproven = [_redact(item) for item in pack.unproven]
    return pack


def finalize_pack(pack: EvidencePack) -> EvidencePack:
    """Redact the pack and recompute the manifest hash."""
    redact_pack(pack)
    pack.manifest_sha256 = canonical_sha256(pack.manifest())
    return pack


def _artifact_name(source: Path, name: str | None) -> str:
    if name:
        value = str(name).replace("\\", "/").strip()
        parts = [part for part in value.split("/") if part not in ("", ".")]
        if parts and ".." not in parts:
            return "/".join(parts)
        return PurePosixPath(parts[-1]).name if parts else "artifact"
    # Absolute host paths are recorded by basename only, so a pack does not
    # leak the user's directory layout.
    if source.is_absolute() or re.match(r"^[A-Za-z]:", str(source)):
        return source.name or "artifact"
    parts = [part for part in str(source).replace("\\", "/").split("/")
             if part not in ("", ".")]
    if not parts or ".." in parts:
        return source.name or "artifact"
    return "/".join(parts)


def artifact_for(
    path: str | Path,
    *,
    artifact_id: str | None = None,
    name: str | None = None,
    media_type: str | None = None,
    created_at: str | None = None,
) -> EvidenceArtifact:
    """Compute the SHA-256 and size of ``path``."""
    source = Path(path)
    try:
        is_file = source.is_file()
    except OSError as exc:
        raise EvidenceError(f"工件无法访问：{source}") from exc
    if not is_file:
        raise EvidenceError(f"工件不存在或不是文件：{source}")

    digest = hashlib.sha256()
    size = 0
    try:
        with source.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
                size += len(chunk)
    except OSError as exc:
        raise EvidenceError(f"工件读取失败：{source}") from exc

    recorded_name = _artifact_name(source, name)
    content_sha = digest.hexdigest()
    resolved_id = artifact_id or (
        "art-" + hashlib.sha256(
            f"{recorded_name}\0{content_sha}".encode("utf-8")
        ).hexdigest()[:16]
    )
    guessed = mimetypes.guess_type(recorded_name)[0] or "application/octet-stream"
    return EvidenceArtifact(
        artifact_id=resolved_id,
        name=recorded_name,
        sha256=content_sha,
        size=size,
        media_type=media_type or guessed,
        created_at=created_at or now_iso(),
    )


def _verification_steps(verification: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(verification, dict):
        return []
    steps = verification.get("steps")
    if isinstance(steps, list) and steps:
        return [step for step in steps if isinstance(step, dict)]
    report = verification.get("report")
    if isinstance(report, dict) and isinstance(report.get("steps"), list):
        return [step for step in report["steps"] if isinstance(step, dict)]
    return []


def _verification_environment(
    verification: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(verification, dict):
        return {}
    report = verification.get("report")
    if isinstance(report, dict) and isinstance(report.get("environment"), dict):
        return report["environment"]
    if isinstance(verification.get("environment"), dict):
        return verification["environment"]
    return {}


def _resolve_commit(
    verification: dict[str, Any] | None,
    repo: dict[str, Any] | None,
    commit: str,
) -> str:
    if str(commit or "").strip():
        return str(commit).strip()
    if isinstance(verification, dict):
        report = verification.get("report")
        if isinstance(report, dict):
            workspace = report.get("workspace")
            if isinstance(workspace, dict) and workspace.get("commit"):
                return str(workspace["commit"])
        if verification.get("commit"):
            return str(verification["commit"])
    if isinstance(repo, dict):
        for key in ("commit", "head_commit", "head"):
            if repo.get(key):
                return str(repo[key])
    return ""


def _environment_from_verification(
    verification: dict[str, Any] | None,
) -> EnvironmentManifest:
    raw = _verification_environment(verification)
    image = str(raw.get("image_digest") or raw.get("image") or "")
    notes: list[str] = []
    raw_notes = raw.get("notes")
    if isinstance(raw_notes, (list, tuple)):
        notes.extend(str(note) for note in raw_notes)
    if image and not _DIGEST_PATTERN.search(image):
        notes.append("镜像记录的是名称或标签，不是内容摘要。")
    versions = raw.get("tool_versions")
    return EnvironmentManifest(
        mode=str(raw.get("mode") or "unknown"),
        os=str(raw.get("os") or ""),
        arch=str(raw.get("arch") or ""),
        isolation=str(raw.get("isolation") or "unknown"),
        network=str(raw.get("network") or "unknown"),
        image_digest=image,
        tool_versions=versions if isinstance(versions, dict) else {},
        working_dir=str(raw.get("working_dir") or ""),
        notes=notes,
    )


def _derived_claim(
    index: int, step: dict[str, Any], commit: str,
) -> tuple[Claim, str | None]:
    """Turn a verification step into a claim plus its unproven note."""
    name = _redact(str(step.get("name") or f"步骤 {index + 1}"))
    command = _redact(str(step.get("command") or ""))
    reason = _redact(str(step.get("reason") or ""))
    raw_status = str(step.get("status") or "not_run").strip().lower()
    notes: list[str] = []
    if command:
        notes.append(f"命令：{command}")

    if raw_status == "passed":
        status, kind = "confirmed", "test_result"
        statement = f"验证步骤「{name}」通过"
        unproven = None
    elif raw_status == "failed":
        status, kind = "failed", "test_result"
        statement = f"验证步骤「{name}」失败" + (f"：{reason}" if reason else "")
        unproven = f"「{name}」验证失败"
    elif raw_status == "skipped":
        status, kind = "not_run", "test_result"
        statement = f"验证步骤「{name}」被跳过" + (f"：{reason}" if reason else "")
        notes.append("原验证状态：skipped")
        unproven = f"「{name}」被跳过，未验证"
    elif raw_status == "not_run":
        status, kind = "not_run", "test_result"
        statement = f"验证步骤「{name}」未运行" + (f"：{reason}" if reason else "")
        unproven = f"「{name}」未运行"
    elif raw_status == "unsupported":
        status, kind = "unsupported", "test_result"
        statement = f"验证步骤「{name}」不受支持" + (f"：{reason}" if reason else "")
        unproven = f"「{name}」当前环境不支持"
    else:
        status, kind = "unverified", "unverified"
        statement = f"验证步骤「{name}」状态未知：{raw_status}"
        notes.append(f"原验证状态：{raw_status}")
        unproven = f"「{name}」状态未知，未验证"

    exit_code = step.get("exit_code")
    if isinstance(exit_code, int) and exit_code >= 0:
        notes.append(f"退出码：{exit_code}")

    claim_id = "step-" + hashlib.sha256(
        f"{index}:{name}:{raw_status}".encode("utf-8")
    ).hexdigest()[:12]
    claim = Claim(
        claim_id=claim_id,
        statement=statement,
        kind=kind,
        status=status,
        commit=commit,
        notes=notes,
    )
    return claim, unproven


def _coerce_claim(item: Claim | dict[str, Any], index: int, commit: str) -> Claim:
    if isinstance(item, Claim):
        claim = Claim.from_dict(item.to_dict())
    elif isinstance(item, dict):
        claim = Claim.from_dict(item)
    else:
        raise EvidenceError(f"claim 格式不正确：第 {index + 1} 项")
    if not claim.claim_id:
        claim.claim_id = "claim-" + hashlib.sha256(
            f"{index}:{claim.statement}".encode("utf-8")
        ).hexdigest()[:12]
    if not claim.commit and commit:
        claim.commit = commit
    return claim


def _text_items(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if not isinstance(value, (list, tuple)):
        return [str(value)]
    return ["" if item is None else str(item) for item in value]


def _dedupe(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def build_pack(
    verification: dict[str, Any] | None = None,
    repo: dict[str, Any] | None = None,
    commit: str = "",
    claims: Sequence[Claim | dict[str, Any]] | None = None,
    artifact_paths: (
        Sequence[str | Path | tuple[str | Path, str]] | str | Path | None
    ) = None,
    environment: EnvironmentManifest | dict[str, Any] | None = None,
    *,
    task_id: str = "",
    pack_id: str | None = None,
    created_at: str | None = None,
    unproven: Sequence[str] | str | None = None,
) -> EvidencePack:
    """Assemble an evidence pack from verification facts and artifact files.

    ``verification`` is the dict returned by ``run_verification`` (top-level
    ``steps`` or ``report.steps``).  Steps that did not pass are preserved as
    failed / not_run / unsupported claims and listed in ``unproven``.
    """
    resolved_commit = _resolve_commit(verification, repo, commit)
    derived_claims: list[Claim] = []
    derived_unproven: list[str] = []
    for index, step in enumerate(_verification_steps(verification)):
        claim, note = _derived_claim(index, step, resolved_commit)
        derived_claims.append(claim)
        if note:
            derived_unproven.append(note)

    all_claims = list(derived_claims)
    all_unproven = list(derived_unproven)
    if isinstance(claims, (Claim, dict)):
        claim_items: list[Any] = [claims]
    else:
        claim_items = list(claims or [])
    for index, item in enumerate(claim_items):
        claim = _coerce_claim(item, index, resolved_commit)
        all_claims.append(claim)
        if claim.status != "confirmed":
            all_unproven.append(
                f"「{claim.statement}」未得到确认（{claim.status}）"
            )

    if isinstance(unproven, str):
        all_unproven.append(unproven)
    elif unproven is not None:
        all_unproven.extend(_text_items(unproven))
    if isinstance(verification, dict):
        all_unproven.extend(_text_items(verification.get("unproven")))

    if isinstance(environment, EnvironmentManifest):
        resolved_environment = EnvironmentManifest.from_dict(environment.to_dict())
    elif environment is not None:
        resolved_environment = EnvironmentManifest.from_dict(environment)
    else:
        resolved_environment = _environment_from_verification(verification)

    entries: list[Any]
    if artifact_paths is None:
        entries = []
    elif isinstance(artifact_paths, (str, Path)):
        entries = [artifact_paths]
    else:
        entries = list(artifact_paths)
    artifacts: list[EvidenceArtifact] = []
    for entry in entries:
        if isinstance(entry, tuple) and len(entry) == 2:
            path, override_name = entry
            artifacts.append(artifact_for(path, name=str(override_name)))
        else:
            artifacts.append(artifact_for(entry))

    repo_id = ""
    if isinstance(repo, dict):
        repo_id = str(repo.get("id") or repo.get("repo_id") or "")

    pack = EvidencePack(
        pack_id=str(pack_id or uuid.uuid4().hex),
        task_id=str(task_id or ""),
        repo_id=repo_id,
        commit=resolved_commit,
        created_at=str(created_at or now_iso()),
        claims=all_claims,
        artifacts=artifacts,
        environment=resolved_environment,
        unproven=_dedupe(all_unproven),
    )
    return finalize_pack(pack)


def _safe_segment(value: str, label: str) -> str:
    segment = str(value or "").strip()
    if not _ID_PATTERN.match(segment):
        raise EvidenceError(f"{label}不合法：{value}")
    return segment


def _pack_path(user_id: int | str, pack_id: str) -> Path:
    user_segment = _safe_segment(str(user_id), "用户 ID")
    pack_segment = _safe_segment(str(pack_id), "证据包 ID")
    return (
        Path(settings.user_data_dir) / user_segment / "evidence"
        / f"{pack_segment}.json"
    )


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent,
    )
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


def save_pack(pack: EvidencePack, user_id: int | str) -> Path:
    """Redact, finalize and atomically save a pack for one user."""
    if not isinstance(pack, EvidencePack):
        raise EvidenceError("证据包格式不正确")
    target = _pack_path(user_id, pack.pack_id)
    finalize_pack(pack)
    payload = json.dumps(pack.to_dict(), ensure_ascii=False, indent=2) + "\n"
    _atomic_write(target, payload.encode("utf-8"))
    return target


def load_pack(user_id: int | str, pack_id: str) -> EvidencePack:
    """Load one user's pack.  Corrupt or foreign packs are not adopted."""
    path = _pack_path(user_id, pack_id)
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise EvidenceError(f"证据包不存在：{pack_id}") from exc
    except OSError as exc:
        raise EvidenceError(f"证据包读取失败：{pack_id}") from exc
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise EvidenceError("证据包文件损坏：不是有效的 JSON") from exc
    try:
        return EvidencePack.from_dict(data)
    except EvidenceError as exc:
        raise EvidenceError(f"证据包文件格式不正确：{exc}") from exc


def list_packs(user_id: int | str) -> list[dict[str, Any]]:
    """Summaries of saved packs, newest first.  Corrupt files are skipped."""
    user_segment = _safe_segment(str(user_id), "用户 ID")
    root = Path(settings.user_data_dir) / user_segment / "evidence"
    if not root.is_dir():
        return []
    items: list[dict[str, Any]] = []
    for path in root.glob("*.json"):
        try:
            pack = EvidencePack.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, EvidenceError):
            continue
        items.append({
            "pack_id": pack.pack_id,
            "task_id": pack.task_id,
            "repo_id": pack.repo_id,
            "commit": pack.commit,
            "created_at": pack.created_at,
            "claims": len(pack.claims),
            "artifacts": len(pack.artifacts),
            "unproven": len(pack.unproven),
            "manifest_sha256": pack.manifest_sha256,
        })
    return sorted(items, key=lambda item: item["created_at"], reverse=True)


def _normalized_artifact_name(name: str) -> str | None:
    value = str(name or "").replace("\\", "/").strip()
    if not value or value.startswith("/") or re.match(r"^[A-Za-z]:", value):
        return None
    parts = [part for part in value.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        return None
    return "/".join(parts)


def _find_artifact(name: str, roots: Sequence[Path]) -> Path | None:
    relative = PurePosixPath(name)
    for root in roots:
        root_resolved = root.resolve()
        candidate = (root_resolved / relative).resolve()
        try:
            candidate.relative_to(root_resolved)
        except ValueError:
            continue
        if candidate.is_file():
            return candidate
        flat = (root_resolved / relative.name).resolve()
        if flat != candidate and flat.is_file():
            return flat
    return None


def _file_digest(path: Path) -> tuple[str, int] | None:
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
                size += len(chunk)
    except OSError:
        return None
    return digest.hexdigest(), size


def _normalize_roots(artifact_roots: Any) -> list[Path]:
    if artifact_roots is None:
        return []
    if isinstance(artifact_roots, (str, Path)):
        items = [artifact_roots]
    elif isinstance(artifact_roots, (list, tuple)):
        items = list(artifact_roots)
    else:
        return []
    return [Path(item) for item in items if str(item or "").strip()]


def verify_pack(pack: Any, artifact_roots: Any) -> dict[str, Any]:
    """Recompute artifact hashes and the manifest hash.

    Returns ``{"ok": bool, "problems": [...]}``.  Malformed input is reported
    as a problem rather than raised, so a corrupt pack cannot crash a caller.
    """
    problems: list[str] = []
    try:
        record = (
            pack if isinstance(pack, EvidencePack) else EvidencePack.from_dict(pack)
        )
    except Exception as exc:  # noqa: BLE001 - malformed input is a reportable fact
        return {"ok": False, "problems": [f"证据包格式不正确：{exc}"]}

    if record.manifest_sha256:
        if record.compute_manifest_sha256() != record.manifest_sha256:
            problems.append(
                "证据包清单摘要不一致：claims/artifacts/environment/unproven "
                "至少有一项被修改"
            )
    else:
        problems.append("证据包缺少清单摘要，无法确认内容完整性")

    roots = _normalize_roots(artifact_roots)
    usable: list[Path] = []
    for root in roots:
        try:
            if root.is_dir():
                usable.append(root)
        except OSError:
            continue
    if record.artifacts and not usable:
        problems.append("没有可用的工件根目录，无法核对工件")

    for artifact in record.artifacts:
        label = artifact.name or artifact.artifact_id or "未命名工件"
        if not artifact.name:
            problems.append(f"工件缺少名称：{artifact.artifact_id or '(无 ID)'}")
            continue
        safe_name = _normalized_artifact_name(artifact.name)
        if safe_name is None:
            problems.append(f"工件路径不安全：{artifact.name}")
            continue
        if not artifact.sha256:
            problems.append(f"工件缺少哈希：{label}")
            continue
        if not usable:
            continue
        found = _find_artifact(safe_name, usable)
        if found is None:
            problems.append(f"工件缺失：{label}")
            continue
        actual = _file_digest(found)
        if actual is None:
            problems.append(f"工件无法读取：{label}")
            continue
        actual_sha, actual_size = actual
        if actual_sha != artifact.sha256:
            problems.append(f"工件内容不一致（可能被篡改）：{label}")
        elif actual_size != artifact.size:
            problems.append(f"工件大小不一致：{label}")

    return {"ok": not problems, "problems": problems}


__all__ = [
    "list_packs",
    "artifact_for", "build_pack", "finalize_pack", "load_pack",
    "redact_pack", "save_pack", "verify_pack",
]

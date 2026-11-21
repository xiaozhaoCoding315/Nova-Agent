"""Compare local and container environments without overclaiming.

Each dimension is reported as ``same``, ``different`` or ``unknown``.  A
dimension is never guessed: if one side did not record it, the result is
``unknown`` and the dimension is not listed as comparable.  A validation run
on the host and a run in a container are only directly comparable when every
recorded dimension matches; even then the note says that matching records do
not guarantee matching results.
"""
from __future__ import annotations

import re
from typing import Any, Callable

from app.core.evidence.models import EnvironmentManifest

DIMENSIONS = (
    "os", "arch", "isolation", "network", "image_digest",
    "tool_versions", "working_dir",
)

_UNKNOWN_MARKERS = {
    "", "unknown", "n/a", "na", "?", "-", "未知", "未记录", "unrecorded",
}
_ARCH_ALIASES = {
    "x86_64": "x86_64",
    "amd64": "x86_64",
    "aarch64": "arm64",
    "arm64": "arm64",
    "i386": "x86",
    "i686": "x86",
    "x86": "x86",
}


def _as_manifest(value: Any) -> EnvironmentManifest:
    if isinstance(value, EnvironmentManifest):
        return value
    if isinstance(value, dict):
        try:
            return EnvironmentManifest.from_dict(value)
        except Exception:  # noqa: BLE001 - malformed input is "not recorded"
            return EnvironmentManifest()
    return EnvironmentManifest()


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _plain(value: str) -> str:
    return value.strip().lower()


def _normalize_os(value: str) -> str:
    return _plain(value)


def _normalize_arch(value: str) -> str:
    lowered = _plain(value)
    return _ARCH_ALIASES.get(lowered, lowered)


def _normalize_isolation(value: str) -> str:
    return _plain(value)


def _normalize_network(value: str) -> str:
    return _plain(value)


def _normalize_image(value: str) -> str:
    # Digests are case-insensitive; image references are compared as written
    # so a tag is not mistaken for a content digest.
    lowered = value.strip().lower()
    if lowered.startswith("sha256:") or "@sha256:" in lowered or re.fullmatch(
        r"[0-9a-f]{64}", lowered
    ):
        return lowered
    return value.strip()


def _normalize_workdir(value: str) -> str:
    text = value.strip().replace("\\", "/")
    text = re.sub(r"/{2,}", "/", text)
    if len(text) > 1 and text.endswith("/"):
        text = text[:-1]
    if len(text) >= 2 and text[1] == ":":
        text = text[0].lower() + text[1:]
    return text


def _is_unknown(value: str) -> bool:
    return _plain(value) in _UNKNOWN_MARKERS


def _side_note(local: str, container: str) -> str:
    if _is_unknown(local) and _is_unknown(container):
        return "两侧都未记录"
    if _is_unknown(local):
        return "本地未记录"
    return "容器未记录"


def _scalar_row(
    dimension: str,
    local_value: Any,
    container_value: Any,
    normalize: Callable[[str], str],
) -> dict[str, Any]:
    local_text = _text(local_value)
    container_text = _text(container_value)
    if _is_unknown(local_text) or _is_unknown(container_text):
        return {
            "dimension": dimension,
            "local": local_text,
            "container": container_text,
            "result": "unknown",
            "note": _side_note(local_text, container_text),
        }
    if normalize(local_text) == normalize(container_text):
        return {
            "dimension": dimension,
            "local": local_text,
            "container": container_text,
            "result": "same",
            "note": "两侧记录一致",
        }
    return {
        "dimension": dimension,
        "local": local_text,
        "container": container_text,
        "result": "different",
        "note": "两侧记录不同",
    }


def _normalize_versions(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    versions: dict[str, str] = {}
    for key, item in value.items():
        name = _text(key).lower()
        if not name:
            continue
        version = _text(item)
        if version:
            versions[name] = version
    return versions


def _tool_versions_row(local_value: Any, container_value: Any) -> dict[str, Any]:
    local = _normalize_versions(local_value)
    container = _normalize_versions(container_value)
    local_display = dict(local)
    container_display = dict(container)

    def row(result: str, note: str) -> dict[str, Any]:
        return {
            "dimension": "tool_versions",
            "local": local_display,
            "container": container_display,
            "result": result,
            "note": note,
        }

    if not local and not container:
        return row("unknown", "两侧都未记录工具版本")
    if not local:
        return row("unknown", "本地未记录工具版本")
    if not container:
        return row("unknown", "容器未记录工具版本")

    common = sorted(set(local) & set(container))
    differing = [name for name in common if local[name] != container[name]]
    only_local = sorted(set(local) - set(container))
    only_container = sorted(set(container) - set(local))
    if differing:
        return row("different", "版本不同的工具：" + "、".join(differing))
    if only_local or only_container:
        sides = []
        if only_local:
            sides.append("仅本地记录：" + "、".join(only_local))
        if only_container:
            sides.append("仅容器记录：" + "、".join(only_container))
        return row("unknown", "；".join(sides) + "；缺少记录不等于一致")
    return row("same", "两侧记录的工具版本一致")


def compare_environments(
    local: EnvironmentManifest | dict[str, Any] | None,
    container: EnvironmentManifest | dict[str, Any] | None,
) -> dict[str, Any]:
    """Return per-dimension comparison rows plus comparable / not lists.

    ``comparable`` contains only dimensions recorded as the same on both
    sides.  ``not_comparable`` contains differences and unknowns; unknowns are
    listed separately in ``unknown`` and never treated as equal.
    """
    local_manifest = _as_manifest(local)
    container_manifest = _as_manifest(container)

    rows = [
        _scalar_row("os", local_manifest.os, container_manifest.os, _normalize_os),
        _scalar_row(
            "arch", local_manifest.arch, container_manifest.arch,
            _normalize_arch,
        ),
        _scalar_row(
            "isolation", local_manifest.isolation,
            container_manifest.isolation, _normalize_isolation,
        ),
        _scalar_row(
            "network", local_manifest.network, container_manifest.network,
            _normalize_network,
        ),
        _scalar_row(
            "image_digest", local_manifest.image_digest,
            container_manifest.image_digest, _normalize_image,
        ),
        _tool_versions_row(
            local_manifest.tool_versions, container_manifest.tool_versions,
        ),
        _scalar_row(
            "working_dir", local_manifest.working_dir,
            container_manifest.working_dir, _normalize_workdir,
        ),
    ]

    comparable = [row["dimension"] for row in rows if row["result"] == "same"]
    different = [row["dimension"] for row in rows if row["result"] == "different"]
    unknown = [row["dimension"] for row in rows if row["result"] == "unknown"]
    not_comparable = [row["dimension"] for row in rows if row["result"] != "same"]
    return {
        "rows": rows,
        "comparable": comparable,
        "not_comparable": not_comparable,
        "different": different,
        "unknown": unknown,
        "identical": bool(rows) and not different and not unknown,
        "note": comparability_note(rows),
    }


def _short(value: Any, limit: int = 60) -> str:
    if isinstance(value, dict):
        text = ", ".join(f"{key}={value[key]}" for key in sorted(value))
    else:
        text = _text(value)
    return text if len(text) <= limit else text[:limit] + "…"


def _detail(rows: list[dict[str, Any]]) -> str:
    parts = []
    for row in rows:
        local = _short(row.get("local")) or "未记录"
        container = _short(row.get("container")) or "未记录"
        parts.append(f"{row['dimension']}（本地 {local}，容器 {container}）")
    return "；".join(parts)


def comparability_note(rows: list[dict[str, Any]] | None) -> str:
    """One plain-Chinese sentence set describing the comparison result."""
    valid = [
        row for row in (rows or [])
        if isinstance(row, dict) and row.get("dimension") in DIMENSIONS
    ]
    if not valid:
        return "没有可比较的环境维度。"

    same = [row for row in valid if row.get("result") == "same"]
    different = [row for row in valid if row.get("result") == "different"]
    unknown = [row for row in valid if row.get("result") == "unknown"]

    parts: list[str] = []
    if same:
        parts.append("以下维度一致：" + "、".join(row["dimension"] for row in same) + "。")
    if different:
        parts.append("以下维度不同：" + _detail(different) + "。这些差异会影响复现。")
    if unknown:
        parts.append("以下维度无法确认：" + _detail(unknown) + "。未记录不等于一致。")
    if not different and not unknown:
        parts.append("记录一致不代表运行结果必然相同，仍以各自环境中的实际验证结果为准。")
    return "".join(parts)


__all__ = ["DIMENSIONS", "comparability_note", "compare_environments"]

"""Redaction for progress and notifications that leave the local process.

Remote surfaces get task ids, coarse status and a short summary.  They never
get source code, absolute paths, credentials, full logs or model output.  The
helpers here are deliberately conservative: when a pattern is ambiguous, drop
the fragment instead of forwarding it.
"""
from __future__ import annotations

import re

MAX_SUMMARY_CHARS = 160

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"), "[凭据]"),
    (re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{10,}\b"), "[凭据]"),
    (re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE), "[凭据]"),
    (re.compile(r"\b[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"), "[凭据]"),
    (re.compile(r"\b[0-9a-fA-F]{32,}\b"), "[凭据]"),
    (re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE), "[链接]"),
    (re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b"), "[邮箱]"),
    (re.compile(r"(?:[A-Za-z]:\\|\\\\)[^\s\"'<>|]+"), "[路径]"),
    (re.compile(r"/(?:home|Users|root|tmp|var|opt|srv|etc|mnt)/[^\s\"'<>]*"), "[路径]"),
    (re.compile(r"\b(?:/[\w.-]+){3,}/?[^\s\"'<>]*"), "[路径]"),
]

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def redact_text(value: object, *, limit: int = MAX_SUMMARY_CHARS) -> str:
    """Return a short, single-line summary with sensitive fragments removed."""
    text = _CONTROL.sub(" ", str(value or ""))
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        text = text[: max(0, limit - 1)].rstrip() + "…"
    return text


__all__ = ["MAX_SUMMARY_CHARS", "redact_text"]

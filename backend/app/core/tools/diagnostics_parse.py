"""Normalize ruff / mypy / tsc output into structured diagnostics.

Pure functions: no execution, no filesystem writes.  Paths that cannot be
mapped back inside the repository are counted in the returned error count
instead of being returned, so a diagnostic never points the client outside
the repo.
"""
import json
import re
from pathlib import Path

from app.core.security.redaction import redact_text

MAX_MESSAGE_CHARS = 1000
MAX_RAW_TAIL_CHARS = 4000

_SEVERITY = {
    "error": "error",
    "warning": "warning",
    "note": "info",
    "message": "info",
    "info": "info",
}

_MYPY_LINE = re.compile(
    r"^(?P<path>.+?):(?P<line>\d+)(?::(?P<col>\d+))?: "
    r"(?P<sev>error|warning|note): (?P<msg>.*?)(?:\s+\[(?P<code>[\w-]+)\])?$"
)
_TSC_LINE = re.compile(
    r"^(?P<path>.+?)\((?P<line>\d+),(?P<col>\d+)\): "
    r"(?P<sev>error|warning|message) TS(?P<code>\d+): (?P<msg>.*)$"
)
_MYPY_SKIP = re.compile(
    r"^(?:Found \d+ errors? in .*|Success: no issues found.*)$"
)
_TSC_SKIP = re.compile(r"^(?:Found \d+ errors?\b.*|Version \d+.*)$")
_TSC_TABLE_HEADER = re.compile(r"^\s*Errors\s+Files\s*$")
_TSC_TABLE_ROW = re.compile(r"^\s*\d+\s+\S+")


def _relative_inside(candidate: Path, root_path: Path) -> str | None:
    try:
        resolved = candidate.resolve(strict=False)
    except (OSError, RuntimeError):
        return None
    try:
        return resolved.relative_to(root_path).as_posix()
    except ValueError:
        return None


def normalize_path(raw: str, root: str | Path) -> str | None:
    """Return a repo-relative POSIX path, or ``None`` when it escapes."""
    text = str(raw or "").strip().strip('"').replace("\\", "/")
    if not text or "\x00" in text:
        return None
    root_path = Path(root).resolve()
    candidate = Path(text)
    if not candidate.is_absolute():
        candidate = root_path / text
    rel_text = _relative_inside(candidate, root_path)
    if rel_text is None and text.startswith("/workspace/"):
        # Sandbox runs with the repo mounted at /workspace; tools that print
        # absolute paths still map back onto the host root.  Strip the prefix
        # only when the remainder lands inside root: a host root that itself
        # lives under /workspace keeps its original text.
        stripped = Path(text.removeprefix("/workspace/"))
        rel_text = _relative_inside(root_path / stripped, root_path)
    if rel_text is None:
        return None
    return rel_text if rel_text and rel_text != "." else None


def _make_diagnostic(
    raw_path: str,
    line,
    column,
    severity: str,
    code,
    message,
    source: str,
    root: str | Path,
) -> dict | None:
    path = normalize_path(raw_path, root)
    if path is None:
        return None
    try:
        line_no = max(0, int(line))
        column_no = max(0, int(column))
    except (TypeError, ValueError):
        line_no, column_no = 0, 0
    return {
        "path": path,
        "line": line_no,
        "column": column_no,
        "severity": _SEVERITY.get(str(severity or "").lower(), "info"),
        "code": str(code or "")[:40],
        "message": redact_text(str(message or "").strip())[:MAX_MESSAGE_CHARS],
        "source": source,
    }


def _append_continuation(
    diagnostics: list[dict], raw_line: str, keep_last: bool
) -> bool:
    """Attach an indented line to the last kept diagnostic.

    Returns ``False`` when there is no kept diagnostic to attach to, so the
    caller can count the orphan line as an error.
    """
    if not keep_last or not diagnostics:
        return False
    joined = diagnostics[-1]["message"] + "\n" + raw_line.strip()
    diagnostics[-1]["message"] = redact_text(joined)[:MAX_MESSAGE_CHARS]
    return True


def parse_ruff_json(
    stdout: str, root: str | Path
) -> tuple[list[dict], int]:
    text = (stdout or "").strip()
    if not text:
        return [], 0
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return [], 1
    if not isinstance(payload, list):
        return [], 1
    diagnostics: list[dict] = []
    errors = 0
    for item in payload:
        if not isinstance(item, dict):
            errors += 1
            continue
        location = item.get("location")
        filename = item.get("filename")
        if not isinstance(location, dict) or not filename:
            errors += 1
            continue
        diagnostic = _make_diagnostic(
            filename,
            location.get("row"),
            location.get("column"),
            "error",
            item.get("code"),
            item.get("message"),
            "ruff",
            root,
        )
        if diagnostic is None:
            errors += 1
        else:
            diagnostics.append(diagnostic)
    return diagnostics, errors


def parse_mypy_text(
    stdout: str, root: str | Path
) -> tuple[list[dict], int]:
    diagnostics: list[dict] = []
    errors = 0
    keep_last = False
    for raw_line in (stdout or "").splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        if line[:1].isspace():
            if not _append_continuation(diagnostics, line, keep_last):
                errors += 1
            continue
        if _MYPY_SKIP.match(line.strip()):
            keep_last = False
            continue
        match = _MYPY_LINE.match(line.strip())
        if not match:
            keep_last = False
            errors += 1
            continue
        diagnostic = _make_diagnostic(
            match.group("path"),
            match.group("line"),
            match.group("col") or 0,
            match.group("sev"),
            match.group("code"),
            match.group("msg"),
            "mypy",
            root,
        )
        if diagnostic is None:
            keep_last = False
            errors += 1
        else:
            diagnostics.append(diagnostic)
            keep_last = True
    return diagnostics, errors


def parse_tsc_text(
    stdout: str, root: str | Path
) -> tuple[list[dict], int]:
    diagnostics: list[dict] = []
    errors = 0
    keep_last = False
    in_summary_table = False
    for raw_line in (stdout or "").splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        if in_summary_table and _TSC_TABLE_ROW.match(line):
            continue
        in_summary_table = False
        if _TSC_TABLE_HEADER.match(line):
            in_summary_table = True
            keep_last = False
            continue
        if line[:1].isspace():
            if not _append_continuation(diagnostics, line, keep_last):
                errors += 1
            continue
        if _TSC_SKIP.match(line.strip()):
            keep_last = False
            continue
        match = _TSC_LINE.match(line.strip())
        if not match:
            keep_last = False
            errors += 1
            continue
        diagnostic = _make_diagnostic(
            match.group("path"),
            match.group("line"),
            match.group("col"),
            match.group("sev"),
            f"TS{match.group('code')}",
            match.group("msg"),
            "tsc",
            root,
        )
        if diagnostic is None:
            keep_last = False
            errors += 1
        else:
            diagnostics.append(diagnostic)
            keep_last = True
    return diagnostics, errors


def sort_diagnostics(diagnostics: list[dict]) -> list[dict]:
    return sorted(
        diagnostics,
        key=lambda item: (
            item["path"], item["line"], item["column"], item["code"],
        ),
    )


def summarize(diagnostics: list[dict]) -> dict:
    return {
        "files": len({item["path"] for item in diagnostics}),
        "errors": sum(1 for item in diagnostics if item["severity"] == "error"),
        "warnings": sum(
            1 for item in diagnostics if item["severity"] == "warning"
        ),
        "total": len(diagnostics),
    }


def tail_text(text: str, limit: int = MAX_RAW_TAIL_CHARS) -> str:
    """Redacted tail of raw runner output, for unparsable lines."""
    if limit <= 0:
        return ""
    # Redact first so a secret straddling the cut is still fully matched.
    return redact_text(text or "")[-limit:]

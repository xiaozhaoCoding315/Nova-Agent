"""Local document workspaces: Markdown master, atomic writes, versions, exports.

The filesystem is the source of truth.  ``.nova/workspace.json`` only records
what the directory is; ``.nova/state.json`` records the last hash this tool
wrote so an external edit can be detected instead of overwritten silently.
Versions live under ``.nova/versions`` and are ordinary files that survive a
database loss.

Nothing in this module needs the database or the network.  PDF export is only
attempted when LibreOffice is installed; a missing tool is reported as
``unsupported`` and never replaced by a server-side conversion.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from app.core.documents.ir import FidelityReport
from app.core.documents.markdown import parse_markdown

WORKSPACE_SCHEMA = "document-workspace-1.0"
WORKSPACE_KINDS = ("report", "thesis", "resume")
MANUSCRIPT_DIR = "manuscripts"
ASSET_DIR = "assets"
SOURCE_DIR = "source"
EXPORT_DIR = "exports"
META_DIR = ".nova"
DEFAULT_MANUSCRIPT = "main.md"
MAX_MANUSCRIPT_BYTES = 4 * 1024 * 1024
EXPORT_TIMEOUT_SECONDS = 180


class WorkspaceError(Exception):
    """A workspace operation could not be completed."""


class WorkspaceConflict(WorkspaceError):
    """The file changed on disk since the caller last read it."""

    def __init__(self, message: str, *, current_sha: str | None = None):
        super().__init__(message)
        self.current_sha = current_sha


class WorkspaceNotFound(WorkspaceError):
    """No workspace or manuscript exists at the requested path."""


@dataclass(frozen=True)
class Workspace:
    root: Path
    id: str
    title: str
    kind: str
    created_at: str
    schema: str = WORKSPACE_SCHEMA

    @property
    def meta_dir(self) -> Path:
        return self.root / META_DIR

    @property
    def manuscript_dir(self) -> Path:
        return self.root / MANUSCRIPT_DIR

    @property
    def export_dir(self) -> Path:
        return self.root / EXPORT_DIR

    def to_dict(self) -> dict:
        return {
            "id": self.id, "title": self.title, "kind": self.kind,
            "created_at": self.created_at, "schema": self.schema,
        }


@dataclass(frozen=True)
class ManuscriptInfo:
    path: str
    size: int
    sha256: str
    updated_at: str

    def to_dict(self) -> dict:
        return {
            "path": self.path, "size": self.size, "sha256": self.sha256,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class VersionInfo:
    version_id: str
    path: str
    sha256: str
    size: int
    created_at: str

    def to_dict(self) -> dict:
        return {
            "version_id": self.version_id, "path": self.path,
            "sha256": self.sha256, "size": self.size,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class WriteResult:
    path: str
    sha256: str
    version: VersionInfo | None
    created: bool

    def to_dict(self) -> dict:
        return {
            "path": self.path, "sha256": self.sha256, "created": self.created,
            "version": self.version.to_dict() if self.version else None,
        }


@dataclass(frozen=True)
class ExportResult:
    status: str
    format: str
    path: str | None
    filename: str | None
    fidelity: dict
    diagnostics: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "status": self.status, "format": self.format, "path": self.path,
            "filename": self.filename, "fidelity": self.fidelity,
            "diagnostics": list(self.diagnostics),
        }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
    _atomic_write(path, (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise WorkspaceNotFound(f"缺少文件：{path.name}") from exc
    except ValueError as exc:
        raise WorkspaceError(f"文件损坏：{path.name}") from exc
    if not isinstance(value, dict):
        raise WorkspaceError(f"文件格式不对：{path.name}")
    return value


def _clean_title(title: str) -> str:
    value = re.sub(r"[\x00-\x1f]", "", (title or "").strip())
    return value[:120] or "未命名文档"


def _normalise_kind(kind: str) -> str:
    value = (kind or "report").strip().lower()
    if value not in WORKSPACE_KINDS:
        raise WorkspaceError(f"不支持的项目类型：{kind}")
    return value


def create_workspace(root: Path | str, *, title: str, kind: str = "report",
                     workspace_id: str | None = None) -> Workspace:
    """Create a workspace.  Refuses to adopt a non-empty unrelated directory."""
    root = Path(root).expanduser().resolve()
    kind = _normalise_kind(kind)
    if root.exists():
        if any(root.iterdir()) and not (root / META_DIR / "workspace.json").exists():
            raise WorkspaceError("目标目录不是空的，且不是 Nova 文档工作区")
    root.mkdir(parents=True, exist_ok=True)
    for name in (MANUSCRIPT_DIR, ASSET_DIR, SOURCE_DIR, EXPORT_DIR, META_DIR):
        (root / name).mkdir(parents=True, exist_ok=True)

    meta_path = root / META_DIR / "workspace.json"
    if meta_path.exists():
        workspace = open_workspace(root)
        return workspace

    workspace = Workspace(
        root=root,
        id=workspace_id or uuid.uuid4().hex,
        title=_clean_title(title),
        kind=kind,
        created_at=_now(),
    )
    _write_json(meta_path, workspace.to_dict())
    _write_json(root / META_DIR / "state.json", {"version": 1, "files": {}})
    _write_json(root / META_DIR / "versions.json", {"version": 1, "paths": {}})
    main = workspace.manuscript_dir / DEFAULT_MANUSCRIPT
    if not main.exists():
        body = f"# {workspace.title}\n\n"
        _atomic_write(main, body.encode("utf-8"))
        _record_state(workspace, DEFAULT_MANUSCRIPT, _sha256_bytes(body.encode("utf-8")))
    return workspace


def open_workspace(root: Path | str) -> Workspace:
    root = Path(root).expanduser().resolve()
    meta = _read_json(root / META_DIR / "workspace.json")
    if meta.get("schema") != WORKSPACE_SCHEMA:
        raise WorkspaceError(f"工作区版本不支持：{meta.get('schema')}")
    kind = str(meta.get("kind") or "report")
    if kind not in WORKSPACE_KINDS:
        raise WorkspaceError(f"工作区类型不支持：{kind}")
    return Workspace(
        root=root,
        id=str(meta.get("id") or ""),
        title=str(meta.get("title") or "未命名文档"),
        kind=kind,
        created_at=str(meta.get("created_at") or ""),
        schema=WORKSPACE_SCHEMA,
    )


def _state_path(workspace: Workspace) -> Path:
    return workspace.meta_dir / "state.json"


def _state(workspace: Workspace) -> dict:
    path = _state_path(workspace)
    if not path.exists():
        return {"version": 1, "files": {}}
    return _read_json(path)


def _record_state(workspace: Workspace, relpath: str, sha256: str) -> None:
    state = _state(workspace)
    files = state.setdefault("files", {})
    if not isinstance(files, dict):
        files = {}
        state["files"] = files
    files[relpath] = {"sha256": sha256, "updated_at": _now()}
    _write_json(_state_path(workspace), state)


def last_known_sha(workspace: Workspace, relpath: str) -> str | None:
    entry = (_state(workspace).get("files") or {}).get(relpath) or {}
    value = entry.get("sha256")
    return str(value) if value else None


def _safe_manuscript_path(workspace: Workspace, relpath: str) -> tuple[str, Path]:
    """Return a normalised ``manuscripts/...`` path and its absolute path."""
    value = (relpath or "").replace("\\", "/").strip()
    if not value or value.startswith("/") or re.match(r"^[A-Za-z]:", value):
        raise WorkspaceError("文件路径必须是工作区内的相对路径")
    parts = [part for part in value.split("/") if part not in ("", ".")]
    if any(part == ".." for part in parts):
        raise WorkspaceError("文件路径不能跳出工作区")
    if len(parts) < 2 or parts[0] != MANUSCRIPT_DIR:
        raise WorkspaceError(f"正文文件必须位于 {MANUSCRIPT_DIR}/ 下")
    if Path(parts[-1]).suffix.lower() != ".md":
        raise WorkspaceError("正文文件必须是 Markdown（.md）")
    relative = "/".join(parts)
    candidate = (workspace.root / relative).resolve()
    try:
        candidate.relative_to(workspace.root)
    except ValueError as exc:
        raise WorkspaceError("文件路径不能跳出工作区") from exc
    return relative, candidate


def resolve_manuscript_path(workspace: Workspace, relpath: str) -> tuple[str, Path]:
    """Public path check for callers that need to test existence first."""
    return _safe_manuscript_path(workspace, relpath)


def list_manuscripts(workspace: Workspace) -> list[ManuscriptInfo]:
    root = workspace.manuscript_dir
    if not root.exists():
        return []
    items: list[ManuscriptInfo] = []
    for path in sorted(root.rglob("*.md")):
        if not path.is_file():
            continue
        relative = path.relative_to(workspace.root).as_posix()
        stat = path.stat()
        items.append(ManuscriptInfo(
            path=relative, size=stat.st_size, sha256=_sha256_file(path),
            updated_at=datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        ))
    return items


def read_manuscript(workspace: Workspace, relpath: str) -> dict:
    relative, path = _safe_manuscript_path(workspace, relpath)
    try:
        data = path.read_bytes()
    except FileNotFoundError as exc:
        raise WorkspaceNotFound(f"正文不存在：{relative}") from exc
    if len(data) > MAX_MANUSCRIPT_BYTES:
        raise WorkspaceError("正文超过 4 MB，文档工作区只编辑文本稿件")
    try:
        content = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise WorkspaceError("正文不是 UTF-8 文本") from exc
    return {
        "path": relative, "content": content,
        "sha256": _sha256_bytes(data), "size": len(data),
        "last_known_sha": last_known_sha(workspace, relative),
    }


def _versions_root(workspace: Workspace) -> Path:
    return workspace.meta_dir / "versions"


def _version_index_path(workspace: Workspace) -> Path:
    return workspace.meta_dir / "versions.json"


def _version_dir(workspace: Workspace, relpath: str) -> Path:
    key = hashlib.sha256(relpath.encode("utf-8")).hexdigest()[:16]
    return _versions_root(workspace) / key


def _snapshot(workspace: Workspace, relative: str, path: Path, sha256: str) -> VersionInfo | None:
    if not path.exists():
        return None
    version_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}-{sha256[:8]}"
    directory = _version_dir(workspace, relative)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{version_id}.md"
    _atomic_write(target, path.read_bytes())
    info = VersionInfo(
        version_id=version_id, path=relative, sha256=sha256,
        size=target.stat().st_size, created_at=_now(),
    )
    index = _read_json(_version_index_path(workspace))
    paths = index.setdefault("paths", {})
    if not isinstance(paths, dict):
        paths = {}
        index["paths"] = paths
    entries = paths.setdefault(relative, [])
    if not isinstance(entries, list):
        entries = []
        paths[relative] = entries
    entries.append(info.to_dict())
    _write_json(_version_index_path(workspace), index)
    return info


def write_manuscript(workspace: Workspace, relpath: str, content: str, *,
                     base_sha: str | None = None, force: bool = False) -> WriteResult:
    """Write a manuscript, refusing to overwrite an unseen external edit."""
    data = content.encode("utf-8")
    if len(data) > MAX_MANUSCRIPT_BYTES:
        raise WorkspaceError("正文超过 4 MB，文档工作区只编辑文本稿件")
    relative, path = _safe_manuscript_path(workspace, relpath)
    exists = path.exists()
    current_sha = _sha256_file(path) if exists else None

    if exists and not force:
        if base_sha is None:
            raise WorkspaceConflict(
                "文件已存在。请先读取，再带上读取时的 sha256 写入；确认覆盖时使用 force。",
                current_sha=current_sha,
            )
        if current_sha != base_sha:
            raise WorkspaceConflict(
                "文件在磁盘上已被外部修改，未写入。请重新读取后再保存。",
                current_sha=current_sha,
            )

    version = _snapshot(workspace, relative, path, current_sha) if exists and current_sha else None
    _atomic_write(path, data)
    new_sha = _sha256_bytes(data)
    _record_state(workspace, relative, new_sha)
    return WriteResult(path=relative, sha256=new_sha, version=version, created=not exists)


def list_versions(workspace: Workspace, relpath: str) -> list[VersionInfo]:
    relative, _ = _safe_manuscript_path(workspace, relpath)
    index = _read_json(_version_index_path(workspace))
    entries = ((index.get("paths") or {}).get(relative) or [])
    result: list[VersionInfo] = []
    for item in reversed(entries if isinstance(entries, list) else []):
        if not isinstance(item, dict):
            continue
        result.append(VersionInfo(
            version_id=str(item.get("version_id") or ""),
            path=relative,
            sha256=str(item.get("sha256") or ""),
            size=int(item.get("size") or 0),
            created_at=str(item.get("created_at") or ""),
        ))
    return result


def restore_version(workspace: Workspace, relpath: str, version_id: str, *,
                    base_sha: str | None = None) -> WriteResult:
    """Restore a snapshot as a new write, so the current file is versioned too."""
    relative, _ = _safe_manuscript_path(workspace, relpath)
    entry = next((item for item in list_versions(workspace, relative)
                  if item.version_id == version_id), None)
    if not entry:
        raise WorkspaceNotFound("找不到该版本")
    key = hashlib.sha256(relative.encode("utf-8")).hexdigest()[:16]
    source = _versions_root(workspace) / key / f"{version_id}.md"
    try:
        content = source.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise WorkspaceNotFound("版本文件已丢失") from exc
    if _sha256_bytes(content.encode("utf-8")) != entry.sha256:
        raise WorkspaceError("版本文件校验失败，内容与索引不一致")
    return write_manuscript(workspace, relative, content, base_sha=base_sha)


def _tool(name: str) -> str | None:
    return shutil.which(name)


def _tool_version(name: str) -> str:
    executable = _tool(name)
    if not executable:
        return ""
    try:
        result = subprocess.run(
            [executable, "--version"], capture_output=True, text=True,
            timeout=15, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    first = (result.stdout or result.stderr or "").strip().splitlines()
    return first[0] if first else ""


def _export_name(workspace: Workspace, source: Path, suffix: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", source.stem).strip("-") or "document"
    target = workspace.export_dir / f"{stem}-{stamp}.{suffix}"
    counter = 2
    while target.exists():
        target = workspace.export_dir / f"{stem}-{stamp}-{counter}.{suffix}"
        counter += 1
    return target


def _fidelity(source_format: str, target_format: str, *, renderer: str,
              diagnostics: list, notes: list[str] | None = None) -> FidelityReport:
    unsupported = sorted({diag.code for diag in diagnostics if diag.severity == "unsupported"})
    return FidelityReport(
        source_format=source_format,
        target_format=target_format,
        preserved=["标题层级", "段落", "列表", "表格", "代码块", "图片引用"]
        if source_format == "markdown" else ["页面版式"],
        modified=[],
        dropped=[],
        unsupported=unsupported,
        notes=(notes or []) + (["源文档包含不支持的对象；导出文件可能缺少这些内容。"]
                               if unsupported else []),
        renderer=renderer,
        renderer_version=_tool_version(renderer),
        template_version=None,
    )


def _export_docx(workspace: Workspace, relative: str, markdown: str) -> ExportResult:
    pandoc = _tool("pandoc")
    if not pandoc:
        return ExportResult(
            status="unsupported", format="docx", path=None, filename=None,
            fidelity=FidelityReport(source_format="markdown", target_format="docx").to_dict(),
            diagnostics=["未找到 Pandoc，无法导出 DOCX。安装 Pandoc 后重试；不会改用服务端转换。"],
        )
    source = workspace.root / relative
    target = _export_name(workspace, source, "docx")
    command = [pandoc, str(source), "-f", "markdown+pipe_tables+footnotes",
               "-t", "docx", "--standalone", "-o", str(target)]
    try:
        result = subprocess.run(
            command, cwd=str(workspace.root), capture_output=True, text=True,
            timeout=EXPORT_TIMEOUT_SECONDS, check=False,
        )
    except subprocess.TimeoutExpired:
        return ExportResult(
            status="failed", format="docx", path=None, filename=None,
            fidelity=FidelityReport(source_format="markdown", target_format="docx").to_dict(),
            diagnostics=[f"Pandoc 导出超时（{EXPORT_TIMEOUT_SECONDS} 秒）。"],
        )
    if result.returncode != 0 or not target.exists():
        target.unlink(missing_ok=True)
        detail = (result.stderr or result.stdout or "").strip()[:500]
        return ExportResult(
            status="failed", format="docx", path=None, filename=None,
            fidelity=FidelityReport(source_format="markdown", target_format="docx").to_dict(),
            diagnostics=[f"Pandoc 导出失败（退出码 {result.returncode}）：{detail}"],
        )

    document = parse_markdown(markdown, document_id=workspace.id, kind=workspace.kind,
                              path=relative, title=source.stem)
    fidelity = _fidelity("markdown", "docx", renderer="pandoc",
                         diagnostics=document.diagnostics,
                         notes=["Markdown 是主控源；DOCX 是导出副本，不回写 Markdown。"])
    sidecar = target.with_suffix(".fidelity.json")
    _write_json(sidecar, fidelity.to_dict())
    return ExportResult(
        status="done", format="docx", path=str(target.relative_to(workspace.root)),
        filename=target.name, fidelity=fidelity.to_dict(),
        diagnostics=[] if fidelity.status() == "exact" else [f"导出保真状态：{fidelity.status()}，请查看保真报告。"],
    )


def _export_pdf(workspace: Workspace, relative: str, markdown: str) -> ExportResult:
    docx_result = _export_docx(workspace, relative, markdown)
    if docx_result.status != "done" or not docx_result.path:
        return ExportResult(
            status="unsupported", format="pdf", path=None, filename=None,
            fidelity=FidelityReport(source_format="markdown", target_format="pdf").to_dict(),
            diagnostics=["PDF 导出依赖 DOCX；DOCX 导出未成功。"] + docx_result.diagnostics,
        )
    soffice = _tool("soffice") or _tool("libreoffice")
    if not soffice:
        return ExportResult(
            status="unsupported", format="pdf", path=None, filename=None,
            fidelity=FidelityReport(source_format="markdown", target_format="pdf").to_dict(),
            diagnostics=[
                "未找到 LibreOffice（soffice），无法导出 PDF。安装后重试；不会改用服务端转换。",
            ],
        )
    docx_path = workspace.root / docx_result.path
    target = _export_name(workspace, docx_path, "pdf")
    command = [soffice, "--headless", "--convert-to", "pdf", "--outdir",
               str(workspace.export_dir), str(docx_path)]
    try:
        result = subprocess.run(
            command, cwd=str(workspace.root), capture_output=True, text=True,
            timeout=EXPORT_TIMEOUT_SECONDS, check=False,
        )
    except subprocess.TimeoutExpired:
        return ExportResult(
            status="failed", format="pdf", path=None, filename=None,
            fidelity=FidelityReport(source_format="markdown", target_format="pdf").to_dict(),
            diagnostics=[f"LibreOffice 导出超时（{EXPORT_TIMEOUT_SECONDS} 秒）。"],
        )
    produced = workspace.export_dir / f"{docx_path.stem}.pdf"
    if result.returncode != 0 or not produced.exists():
        detail = (result.stderr or result.stdout or "").strip()[:500]
        return ExportResult(
            status="failed", format="pdf", path=None, filename=None,
            fidelity=FidelityReport(source_format="markdown", target_format="pdf").to_dict(),
            diagnostics=[f"LibreOffice 导出失败（退出码 {result.returncode}）：{detail}"],
        )
    if produced != target:
        os.replace(produced, target)
    fidelity = FidelityReport(
        source_format="markdown", target_format="pdf",
        preserved=["页面版式（由 LibreOffice 渲染）"],
        modified=[], dropped=[],
        unsupported=docx_result.fidelity.get("unsupported", []),
        notes=[
            "PDF 是终态导出，不能作为可逆编辑源。",
            "PDF 保真度取决于 LibreOffice 的字体与渲染环境。",
        ],
        renderer="libreoffice", renderer_version=_tool_version(
            "soffice" if _tool("soffice") else "libreoffice"
        ),
        template_version=None,
    )
    _write_json(target.with_suffix(".fidelity.json"), fidelity.to_dict())
    return ExportResult(
        status="done", format="pdf", path=str(target.relative_to(workspace.root)),
        filename=target.name, fidelity=fidelity.to_dict(),
        diagnostics=["PDF 不能反向编辑；需要修改请改 Markdown 源文件后重新导出。"],
    )


def export_manuscript(workspace: Workspace, relpath: str, fmt: str) -> ExportResult:
    relative, path = _safe_manuscript_path(workspace, relpath)
    if not path.exists():
        raise WorkspaceNotFound(f"正文不存在：{relative}")
    if fmt not in ("docx", "pdf"):
        raise WorkspaceError("只支持导出 docx 或 pdf")
    content = read_manuscript(workspace, relative)["content"]
    if fmt == "docx":
        return _export_docx(workspace, relative, content)
    return _export_pdf(workspace, relative, content)


def workspace_diagnostics(workspace: Workspace) -> dict:
    files = list_manuscripts(workspace)
    unreadable: list[str] = []
    unsupported: Counter[str] = Counter()
    for item in files:
        try:
            document = parse_markdown(
                read_manuscript(workspace, item.path)["content"],
                document_id=workspace.id, kind=workspace.kind, path=item.path,
            )
        except WorkspaceError as exc:
            unreadable.append(f"{item.path}: {exc}")
            continue
        for diagnostic in document.unsupported_diagnostics():
            unsupported[diagnostic.code] += 1
    return {
        "workspace": workspace.to_dict(),
        "manuscripts": len(files),
        "unreadable": unreadable,
        "unsupported": dict(sorted(unsupported.items())),
        "tools": {
            "pandoc": bool(_tool("pandoc")),
            "libreoffice": bool(_tool("soffice") or _tool("libreoffice")),
        },
        "schema_version": WORKSPACE_SCHEMA,
    }


__all__ = [
    "DEFAULT_MANUSCRIPT", "EXPORT_DIR", "MANUSCRIPT_DIR", "META_DIR",
    "WORKSPACE_KINDS", "WORKSPACE_SCHEMA", "ExportResult", "ManuscriptInfo",
    "VersionInfo", "Workspace", "WorkspaceConflict", "WorkspaceError",
    "WorkspaceNotFound", "WriteResult", "create_workspace", "export_manuscript",
    "last_known_sha", "list_manuscripts", "list_versions", "open_workspace",
    "read_manuscript", "resolve_manuscript_path", "restore_version",
    "workspace_diagnostics", "write_manuscript",
]

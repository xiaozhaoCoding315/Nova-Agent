"""Document conversion pipelines: Markdown -> DOCX, Markdown -> PDF, DOCX -> PDF.

External tools do the real work: Pandoc renders Markdown into DOCX (using a
generated reference document so the profile's page size, margins, fonts and
line spacing are applied), and LibreOffice renders DOCX into PDF.  A missing
tool is reported as ``unsupported`` with a Chinese diagnostic; this module
never substitutes a server-side renderer and never reports a fake success.

Every successful conversion writes a JSON fidelity sidecar next to the output
(``<output>.fidelity.json``) that records what was preserved, changed, dropped,
or is not supported.  Outputs are staged inside the output directory and moved
into place atomically, so a failed conversion leaves no partial artifact.

Profiles are conservative generic defaults.  They are *not* a claim of
compliance with any school, journal, or institutional template; callers must
review the target requirements themselves.

PDF is treated as a terminal format.  PDF -> DOCX (or any reverse editing) is
rejected explicitly instead of being guessed at.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

CONVERSION_SCHEMA = "document-conversion-1.0"
CONVERT_TIMEOUT_SECONDS = 180
PAGE_SIZES_MM = {
    "a4": (210.0, 297.0),
    "letter": (215.9, 279.4),
}
MARKDOWN_SUFFIXES = (".md", ".markdown")
SUPPORTED_TARGETS = ("docx", "pdf")
CONSERVATIVE_NOTE = (
    "这是通用默认配置，不保证符合具体学校、期刊或机构的模板与格式要求；"
    "请按目标单位的规范自行核对和调整。"
)

_HEADING_RE = re.compile(r"^#{1,6}\s+\S", re.M)
_LIST_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+\S", re.M)
_TABLE_SEPARATOR_RE = re.compile(
    r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$", re.M,
)
_FOOTNOTE_RE = re.compile(r"\[\^[^\]]+\]")
_FENCE_RE = re.compile(r"^\s*(?:```|~~~)", re.M)
_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]+\)")
_LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\([^)]+\)")
_HTML_BLOCK_RE = re.compile(
    r"^\s*<(?:!doctype|html|div|table|p|span|br|h[1-6]|ul|ol|li)\b", re.I | re.M,
)
_HTML_INLINE_RE = re.compile(r"</?[A-Za-z][A-Za-z0-9-]*(?:\s[^<>]*)?/?>")
_MATH_BLOCK_RE = re.compile(r"^\s*\$\$\s*$", re.M)
_MATH_INLINE_RE = re.compile(r"(?<!\$)\$(?!\$)[^$\n]+\$(?!\$)")


class ConversionError(Exception):
    """A conversion request is invalid or cannot be completed."""


@dataclass(frozen=True)
class ConversionProfile:
    """A small, explicit page/typography profile for generated DOCX files."""

    name: str
    page_size: str
    margin_mm: float
    font: str
    font_size_pt: float
    line_spacing: float
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "page_size": self.page_size,
            "margin_mm": self.margin_mm,
            "font": self.font,
            "font_size_pt": self.font_size_pt,
            "line_spacing": self.line_spacing,
            "notes": list(self.notes),
        }


PROFILES: dict[str, ConversionProfile] = {
    "report": ConversionProfile(
        name="report",
        page_size="A4",
        margin_mm=25.0,
        font="宋体",
        font_size_pt=12.0,
        line_spacing=1.5,
        notes=(
            CONSERVATIVE_NOTE,
            "报告配置只设置页面、基础字体、字号与行距；页眉页脚、编号和目录需在 Word 中另行处理。",
        ),
    ),
    "thesis": ConversionProfile(
        name="thesis",
        page_size="A4",
        margin_mm=30.0,
        font="宋体",
        font_size_pt=12.0,
        line_spacing=1.5,
        notes=(
            CONSERVATIVE_NOTE,
            "学位论文通常另有封面、页眉页脚、章节编号、图表题注和参考文献样式要求，本配置未覆盖这些内容。",
        ),
    ),
    "resume": ConversionProfile(
        name="resume",
        page_size="A4",
        margin_mm=15.0,
        font="微软雅黑",
        font_size_pt=10.5,
        line_spacing=1.15,
        notes=(
            CONSERVATIVE_NOTE,
            "简历模板差异很大；本配置只提供较紧凑的基础版式。",
        ),
    ),
}


def get_profile(name: str) -> ConversionProfile:
    """Return a built-in profile, rejecting unknown names instead of guessing."""
    key = (name or "report").strip().lower()
    profile = PROFILES.get(key)
    if profile is None:
        available = "、".join(sorted(PROFILES))
        raise ConversionError(f"未知的转换配置：{name}；可用配置：{available}")
    return profile


@dataclass(frozen=True)
class ConversionResult:
    """Outcome of one conversion request.

    ``status`` is ``done``, ``unsupported`` or ``failed``.  ``output_path`` is
    the final artifact; for an unsupported Markdown -> PDF request that still
    preserved an intermediate DOCX, it points at that DOCX while ``status``
    remains ``unsupported``.  A conversion is never reported as ``done`` when
    the requested target does not exist.
    """

    status: str
    output_path: str | None
    fidelity_path: str | None
    fidelity: dict
    diagnostics: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "output_path": self.output_path,
            "fidelity_path": self.fidelity_path,
            "fidelity": self.fidelity,
            "diagnostics": list(self.diagnostics),
        }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
    lines = (result.stdout or result.stderr or "").strip().splitlines()
    return lines[0] if lines else ""


def _libreoffice_version() -> str:
    for name in ("soffice", "libreoffice"):
        if _tool(name):
            return _tool_version(name)
    return ""


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


def _sidecar_path(output: Path) -> Path:
    # Literal contract: <output>.fidelity.json (the extension is kept).
    return output.with_name(output.name + ".fidelity.json")


def resolve_output_path(output_dir: Path | str, filename: str) -> Path:
    """Resolve a filename inside ``output_dir`` or reject it.

    This is the single path guard used by :func:`convert_document`; it rejects
    absolute names, drive letters, ``..`` segments and anything that resolves
    outside the output directory.
    """
    root = Path(output_dir).expanduser().resolve()
    raw = str(filename or "").replace("\\", "/").strip()
    if not raw:
        raise ConversionError("输出文件名不能为空")
    if re.search(r"[\x00-\x1f]", raw):
        raise ConversionError("输出文件名包含控制字符")
    if raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
        raise ConversionError("输出路径必须是输出目录内的相对路径")
    parts = [part for part in raw.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        raise ConversionError("输出路径不能跳出输出目录")
    candidate = (root / "/".join(parts)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ConversionError("输出路径不能跳出输出目录") from exc
    return candidate


def _normalise_target(target_format: str) -> str:
    value = (target_format or "").strip().lower().lstrip(".")
    if value in ("", "md", "markdown"):
        raise ConversionError(f"不支持的目标格式：{target_format}；目前支持 DOCX 与 PDF")
    if value not in SUPPORTED_TARGETS:
        available = "、".join(item.upper() for item in SUPPORTED_TARGETS)
        raise ConversionError(f"不支持的目标格式：{target_format}；目前支持 {available}")
    return value


def _source_format(source: Path) -> str:
    suffix = source.suffix.lower()
    if suffix in MARKDOWN_SUFFIXES:
        return "markdown"
    if suffix == ".docx":
        return "docx"
    if suffix == ".pdf":
        return "pdf"
    raise ConversionError(
        f"不支持的源文件类型：{source.suffix or '（无扩展名）'}；只支持 Markdown 或 DOCX"
    )


def _check_pair(source_format: str, target_format: str) -> None:
    if source_format == "pdf":
        if target_format == "docx":
            raise ConversionError(
                "不支持 PDF -> DOCX：PDF 是终态格式，本工具不做任意反向编辑；"
                "请提供原始 Markdown 或 DOCX 源文件。"
            )
        raise ConversionError(
            "不支持从 PDF 转换：PDF 是终态格式，请提供 Markdown 或 DOCX 源文件。"
        )
    if source_format == "docx" and target_format == "docx":
        raise ConversionError("源文件与目标格式相同，无需转换。")
    if not (
        source_format == "markdown"
        and target_format in ("docx", "pdf")
        or source_format == "docx"
        and target_format == "pdf"
    ):
        raise ConversionError(f"不支持 {source_format} -> {target_format} 的转换。")


def _output_name(source: Path, target_format: str) -> str:
    stem = re.sub(r"[\x00-\x1f]", "", source.stem).strip()
    stem = stem.replace("/", "-").replace("\\", "-")
    if stem in ("", ".", ".."):
        stem = "document"
    return f"{stem}.{target_format}"


def _read_markdown(source: Path) -> str:
    try:
        text = source.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ConversionError("Markdown 源文件不是 UTF-8 文本") from exc
    except OSError as exc:
        raise ConversionError(f"无法读取源文件：{exc}") from exc
    return text.lstrip("﻿")


def _add_unique(items: list[str], label: str) -> None:
    if label not in items:
        items.append(label)


def _analyse_markdown(text: str) -> tuple[list[str], list[str], list[str], list[str]]:
    """Return ``(preserved, changed, dropped, unsupported)`` for a Markdown source.

    Tables and footnotes are preserved by Pandoc's DOCX writer.  Raw HTML and
    math are reported as unsupported/lossy even though Pandoc may render some
    of them, because their fidelity depends on the target and is not checked.
    """
    preserved: list[str] = []
    changed: list[str] = []
    dropped: list[str] = []
    unsupported: list[str] = []

    _add_unique(preserved, "段落")
    if _HEADING_RE.search(text):
        _add_unique(preserved, "标题层级")
    if _LIST_RE.search(text):
        _add_unique(preserved, "列表")
    if _TABLE_SEPARATOR_RE.search(text):
        _add_unique(preserved, "表格")
    if _FOOTNOTE_RE.search(text):
        _add_unique(preserved, "脚注")
    if _FENCE_RE.search(text):
        _add_unique(preserved, "代码块")
    if _IMAGE_RE.search(text):
        _add_unique(preserved, "图片引用")
    if _LINK_RE.search(text):
        _add_unique(preserved, "超链接")

    if _HTML_BLOCK_RE.search(text):
        _add_unique(unsupported, "html_block")
    elif _HTML_INLINE_RE.search(text):
        _add_unique(unsupported, "html_inline")
    if _MATH_BLOCK_RE.search(text):
        _add_unique(unsupported, "math_block")
    if _MATH_INLINE_RE.search(text):
        _add_unique(unsupported, "math_inline")
    return preserved, changed, dropped, unsupported


def _fidelity_status(
    preserved: list[str], changed: list[str], dropped: list[str], unsupported: list[str],
) -> str:
    if dropped or unsupported:
        return "lossy"
    if changed:
        return "partial"
    return "exact"


def _fidelity_payload(
    *,
    source: Path,
    target: Path,
    profile: ConversionProfile,
    status: str,
    preserved: list[str],
    changed: list[str],
    dropped: list[str],
    unsupported: list[str],
    tool_versions: dict[str, str],
    notes: list[str],
) -> dict:
    return {
        "schema": CONVERSION_SCHEMA,
        "source": source.name,
        "target": target.name,
        "profile": profile.name,
        "profile_settings": profile.to_dict(),
        "status": status,
        "preserved": list(preserved),
        "changed": list(changed),
        "dropped": list(dropped),
        "unsupported": list(unsupported),
        "tool_versions": dict(tool_versions),
        "notes": list(notes),
        "created_at": _now(),
    }


def _write_sidecar(output: Path, payload: dict) -> Path:
    sidecar = _sidecar_path(output)
    _write_json(sidecar, payload)
    return sidecar


def _staging_dir(output_dir: Path) -> Path:
    return Path(tempfile.mkdtemp(prefix=".convert-", dir=str(output_dir)))


def _unique_sibling(path: Path) -> Path:
    counter = 2
    candidate = path
    while candidate.exists():
        candidate = path.with_name(f"{path.stem}-{counter}{path.suffix}")
        counter += 1
    return candidate


def _run(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        command, cwd=str(cwd), capture_output=True, text=True,
        timeout=CONVERT_TIMEOUT_SECONDS, check=False,
    )


def _set_east_asian_font(style, font: str) -> None:
    from docx.oxml.ns import qn

    rpr = style.element.get_or_add_rPr()
    rfonts = rpr.get_or_add_rFonts()
    for attr in ("w:eastAsia", "w:ascii", "w:hAnsi"):
        rfonts.set(qn(attr), font)


def _build_reference_docx(path: Path, profile: ConversionProfile) -> None:
    """Generate a Pandoc reference DOCX that carries the profile's layout."""
    try:
        from docx import Document
        from docx.enum.style import WD_STYLE_TYPE
        from docx.shared import Mm, Pt, RGBColor
    except ImportError as exc:  # pragma: no cover - python-docx is a dependency
        raise ConversionError(
            "缺少 python-docx，无法应用版式配置；请先安装 python-docx。"
        ) from exc

    size = PAGE_SIZES_MM.get(profile.page_size.strip().lower())
    if size is None:
        raise ConversionError(f"未知页面尺寸：{profile.page_size}")

    document = Document()
    section = document.sections[0]
    section.page_width = Mm(size[0])
    section.page_height = Mm(size[1])
    section.top_margin = Mm(profile.margin_mm)
    section.bottom_margin = Mm(profile.margin_mm)
    section.left_margin = Mm(profile.margin_mm)
    section.right_margin = Mm(profile.margin_mm)

    body_styles = (
        "Normal", "Body Text", "First Paragraph", "Compact",
        "Block Text", "Footnote Text",
    )
    for style_name in body_styles:
        try:
            style = document.styles[style_name]
        except KeyError:
            if style_name == "Normal":
                raise
            style = document.styles.add_style(style_name, WD_STYLE_TYPE.PARAGRAPH)
            style.base_style = document.styles["Normal"]
        style.font.name = profile.font
        style.font.size = Pt(profile.font_size_pt)
        style.paragraph_format.line_spacing = profile.line_spacing
        _set_east_asian_font(style, profile.font)

    for style in document.styles:
        if style.type != WD_STYLE_TYPE.PARAGRAPH:
            continue
        if style.name == "Title" or style.name.startswith("Heading"):
            style.font.name = profile.font
            style.font.color.rgb = RGBColor(0, 0, 0)
            _set_east_asian_font(style, profile.font)

    document.save(str(path))


def _run_pandoc_docx(
    pandoc: str,
    source_path: Path,
    output: Path,
    staging: Path,
    profile: ConversionProfile,
) -> tuple[bool, str]:
    reference = staging / "reference.docx"
    try:
        _build_reference_docx(reference, profile)
    except (OSError, ValueError, ConversionError) as exc:
        return False, f"无法生成版式参考文档：{exc}"

    command = [
        pandoc, str(source_path),
        "-f", "markdown+pipe_tables+footnotes",
        "-t", "docx",
        "--standalone",
        "--reference-doc", str(reference),
        "-o", str(output),
    ]
    try:
        result = _run(command, cwd=source_path.parent)
    except subprocess.TimeoutExpired:
        return False, f"Pandoc 转换超时（{CONVERT_TIMEOUT_SECONDS} 秒）。"
    except OSError as exc:
        return False, f"无法启动 Pandoc：{exc}"

    if result.returncode != 0 or not output.exists() or output.stat().st_size == 0:
        detail = (result.stderr or result.stdout or "").strip()[:500]
        return False, (
            f"Pandoc 转换失败（退出码 {result.returncode}）："
            f"{detail or '未生成输出文件'}"
        )
    return True, ""


def _run_soffice_pdf(
    soffice: str,
    docx_path: Path,
    staging: Path,
    target: Path,
) -> tuple[bool, str]:
    profile_dir = staging / "lo-profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    command = [
        soffice,
        f"-env:UserInstallation={profile_dir.resolve().as_uri()}",
        "--headless", "--norestore",
        "--convert-to", "pdf",
        "--outdir", str(staging),
        str(docx_path),
    ]
    try:
        result = _run(command, cwd=staging)
    except subprocess.TimeoutExpired:
        return False, f"LibreOffice 转换超时（{CONVERT_TIMEOUT_SECONDS} 秒）。"
    except OSError as exc:
        return False, f"无法启动 LibreOffice：{exc}"

    produced = staging / f"{docx_path.stem}.pdf"
    if not produced.exists():
        candidates = sorted(staging.glob("*.pdf"))
        if len(candidates) == 1:
            produced = candidates[0]
    if result.returncode != 0 or not produced.exists() or produced.stat().st_size == 0:
        detail = (result.stderr or result.stdout or "").strip()[:500]
        return False, (
            f"LibreOffice 转换失败（退出码 {result.returncode}）："
            f"{detail or '未生成 PDF 文件'}"
        )
    os.replace(produced, target)
    return True, ""


def _failure_result(
    *,
    status: str,
    source: Path,
    target: Path,
    profile: ConversionProfile,
    preserved: list[str],
    changed: list[str],
    dropped: list[str],
    unsupported: list[str],
    tool_versions: dict[str, str],
    notes: list[str],
    diagnostics: list[str],
    output_path: str | None = None,
) -> ConversionResult:
    payload = _fidelity_payload(
        source=source, target=target, profile=profile,
        status="unsupported",
        preserved=preserved, changed=changed, dropped=dropped,
        unsupported=unsupported, tool_versions=tool_versions,
        notes=notes + list(diagnostics),
    )
    return ConversionResult(
        status=status, output_path=output_path, fidelity_path=None,
        fidelity=payload, diagnostics=list(diagnostics),
    )


def _convert_markdown_to_docx(
    source_path: Path,
    target: Path,
    output_dir: Path,
    profile: ConversionProfile,
    preserved: list[str],
    changed: list[str],
    dropped: list[str],
    unsupported: list[str],
    notes: list[str],
) -> ConversionResult:
    pandoc = _tool("pandoc")
    tool_versions = {"pandoc": _tool_version("pandoc"), "libreoffice": ""}
    if not pandoc:
        diagnostics = [
            "未找到 Pandoc，无法转换 Markdown。安装 Pandoc 后重试；不会改用服务端转换。",
        ]
        return _failure_result(
            status="unsupported", source=source_path, target=target, profile=profile,
            preserved=preserved, changed=changed, dropped=dropped,
            unsupported=unsupported, tool_versions=tool_versions,
            notes=notes, diagnostics=diagnostics,
        )

    staging = _staging_dir(output_dir)
    try:
        staged_output = staging / "output.docx"
        ok, diagnostic = _run_pandoc_docx(
            pandoc, source_path, staged_output, staging, profile,
        )
        if not ok:
            return _failure_result(
                status="failed", source=source_path, target=target, profile=profile,
                preserved=preserved, changed=changed, dropped=dropped,
                unsupported=unsupported, tool_versions=tool_versions,
                notes=notes, diagnostics=[diagnostic],
            )

        os.replace(staged_output, target)
        status = _fidelity_status(preserved, changed, dropped, unsupported)
        payload = _fidelity_payload(
            source=source_path, target=target, profile=profile, status=status,
            preserved=preserved, changed=changed, dropped=dropped,
            unsupported=unsupported, tool_versions=tool_versions, notes=notes,
        )
        sidecar = _write_sidecar(target, payload)
        diagnostics: list[str] = []
        if status == "lossy":
            diagnostics.append(
                "转换包含已知损失：" + "、".join(dropped + unsupported)
                + "；已按 allow_lossy=True 继续。"
            )
        return ConversionResult(
            status="done", output_path=str(target), fidelity_path=str(sidecar),
            fidelity=payload, diagnostics=diagnostics,
        )
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _preserve_intermediate(
    intermediate: Path, output_dir: Path, filename: str, *, overwrite: bool,
) -> Path:
    target = resolve_output_path(output_dir, filename)
    if target.exists() and not overwrite:
        target = _unique_sibling(target)
    os.replace(intermediate, target)
    return target


def _convert_markdown_to_pdf(
    source_path: Path,
    target: Path,
    output_dir: Path,
    profile: ConversionProfile,
    preserved: list[str],
    changed: list[str],
    dropped: list[str],
    unsupported: list[str],
    notes: list[str],
    *,
    overwrite: bool,
) -> ConversionResult:
    pandoc = _tool("pandoc")
    pandoc_version = _tool_version("pandoc")
    lib_version = _libreoffice_version()
    if not pandoc:
        diagnostics = [
            "未找到 Pandoc，无法先生成中间 DOCX，因此也不能生成 PDF。"
            "安装 Pandoc 后重试；不会改用服务端转换。",
        ]
        return _failure_result(
            status="unsupported", source=source_path, target=target, profile=profile,
            preserved=preserved, changed=changed, dropped=dropped,
            unsupported=unsupported,
            tool_versions={"pandoc": "", "libreoffice": lib_version},
            notes=notes, diagnostics=diagnostics,
        )

    staging = _staging_dir(output_dir)
    try:
        intermediate = staging / f"{target.stem}.docx"
        ok, diagnostic = _run_pandoc_docx(
            pandoc, source_path, intermediate, staging, profile,
        )
        if not ok:
            return _failure_result(
                status="failed", source=source_path, target=target, profile=profile,
                preserved=preserved, changed=changed, dropped=dropped,
                unsupported=unsupported,
                tool_versions={"pandoc": pandoc_version, "libreoffice": lib_version},
                notes=notes, diagnostics=[diagnostic],
            )

        soffice = _tool("soffice") or _tool("libreoffice")
        if not soffice:
            preserved_docx = _preserve_intermediate(
                intermediate, output_dir, f"{target.stem}.docx", overwrite=overwrite,
            )
            diagnostics = [
                "未找到 LibreOffice（soffice），无法生成 PDF；已保留中间 DOCX："
                f"{preserved_docx.name}。安装 LibreOffice 后重试；不会改用服务端转换。",
            ]
            return _failure_result(
                status="unsupported", source=source_path, target=target,
                profile=profile,
                preserved=preserved, changed=changed, dropped=dropped,
                unsupported=unsupported,
                tool_versions={"pandoc": pandoc_version, "libreoffice": ""},
                notes=notes, diagnostics=diagnostics,
                output_path=str(preserved_docx),
            )

        ok, diagnostic = _run_soffice_pdf(soffice, intermediate, staging, target)
        if not ok:
            return _failure_result(
                status="failed", source=source_path, target=target, profile=profile,
                preserved=preserved, changed=changed, dropped=dropped,
                unsupported=unsupported,
                tool_versions={"pandoc": pandoc_version, "libreoffice": lib_version},
                notes=notes, diagnostics=[diagnostic],
            )

        pdf_changed = changed + ["分页、字体替换与渲染细节由 LibreOffice 决定"]
        status = _fidelity_status(preserved, pdf_changed, dropped, unsupported)
        pdf_notes = notes + [
            "PDF 是终态导出，不能作为可逆编辑源。",
            "PDF 保真度取决于 LibreOffice 与系统可用字体。",
        ]
        payload = _fidelity_payload(
            source=source_path, target=target, profile=profile, status=status,
            preserved=preserved, changed=pdf_changed, dropped=dropped,
            unsupported=unsupported,
            tool_versions={"pandoc": pandoc_version, "libreoffice": lib_version},
            notes=pdf_notes,
        )
        sidecar = _write_sidecar(target, payload)
        diagnostics = ["PDF 不能反向编辑；需要修改请改 Markdown 源文件后重新导出。"]
        if status == "lossy":
            diagnostics.append(
                "转换包含已知损失：" + "、".join(dropped + unsupported)
                + "；已按 allow_lossy=True 继续。"
            )
        return ConversionResult(
            status="done", output_path=str(target), fidelity_path=str(sidecar),
            fidelity=payload, diagnostics=diagnostics,
        )
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _convert_docx_to_pdf(
    source_path: Path,
    target: Path,
    output_dir: Path,
    profile: ConversionProfile,
) -> ConversionResult:
    preserved = ["文字与段落", "页面版式（由 DOCX 定义）"]
    changed = ["分页、字体替换与渲染细节由 LibreOffice 和系统可用字体决定"]
    notes = [
        "PDF 是终态导出，不能作为可逆编辑源。",
        "PDF 保真度取决于 LibreOffice 与系统可用字体。",
    ]
    soffice = _tool("soffice") or _tool("libreoffice")
    if not soffice:
        diagnostics = [
            "未找到 LibreOffice（soffice），无法生成 PDF。源 DOCX 保持不变；"
            "安装 LibreOffice 后重试；不会改用服务端转换。",
        ]
        return _failure_result(
            status="unsupported", source=source_path, target=target, profile=profile,
            preserved=preserved, changed=changed, dropped=[], unsupported=[],
            tool_versions={"pandoc": "", "libreoffice": ""},
            notes=notes, diagnostics=diagnostics,
        )

    staging = _staging_dir(output_dir)
    try:
        ok, diagnostic = _run_soffice_pdf(soffice, source_path, staging, target)
        if not ok:
            return _failure_result(
                status="failed", source=source_path, target=target, profile=profile,
                preserved=preserved, changed=changed, dropped=[], unsupported=[],
                tool_versions={"pandoc": "", "libreoffice": _libreoffice_version()},
                notes=notes, diagnostics=[diagnostic],
            )
        payload = _fidelity_payload(
            source=source_path, target=target, profile=profile, status="partial",
            preserved=preserved, changed=changed, dropped=[], unsupported=[],
            tool_versions={"pandoc": "", "libreoffice": _libreoffice_version()},
            notes=notes,
        )
        sidecar = _write_sidecar(target, payload)
        return ConversionResult(
            status="done", output_path=str(target), fidelity_path=str(sidecar),
            fidelity=payload,
            diagnostics=["PDF 不能反向编辑；需要修改请改 DOCX 源文件后重新导出。"],
        )
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def convert_document(
    source: Path | str,
    target_format: str,
    output_dir: Path | str,
    *,
    profile: str = "report",
    overwrite: bool = False,
    allow_lossy: bool = False,
) -> ConversionResult:
    """Convert ``source`` into ``output_dir`` using Pandoc/LibreOffice.

    Supported: Markdown -> DOCX, Markdown -> PDF (DOCX then LibreOffice) and
    DOCX -> PDF.  PDF sources are rejected because PDF is terminal.  A missing
    tool returns ``status="unsupported"`` with diagnostics and no output.
    Lossy Markdown (raw HTML, math) requires ``allow_lossy=True``.

    Raises :class:`ConversionError` for invalid requests (unsupported pair,
    unknown profile, path escape, existing target without ``overwrite``).
    """
    source_path = Path(source).expanduser().resolve()
    target_kind = _normalise_target(target_format)
    profile_obj = get_profile(profile)
    if not source_path.exists() or not source_path.is_file():
        raise ConversionError(f"源文件不存在：{source}")
    source_kind = _source_format(source_path)
    _check_pair(source_kind, target_kind)

    out_root = Path(output_dir).expanduser()
    try:
        out_root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ConversionError(f"无法创建输出目录：{exc}") from exc
    out_root = out_root.resolve()
    target = resolve_output_path(out_root, _output_name(source_path, target_kind))
    if target.exists() and not overwrite:
        raise ConversionError(
            f"目标文件已存在：{target.name}；如需覆盖，请设置 overwrite=True。"
        )

    if source_kind == "markdown":
        text = _read_markdown(source_path)
        preserved, changed, dropped, unsupported = _analyse_markdown(text)
        notes = ["Markdown 是主控源；导出文件是副本，不回写 Markdown。"]
        notes.extend(profile_obj.notes)
        if "表格" in preserved:
            notes.append("表格文字与结构会保留；表格样式由 Pandoc 与 Word 默认样式决定。")
        status = _fidelity_status(preserved, changed, dropped, unsupported)
        if status == "lossy" and not allow_lossy:
            raise ConversionError(
                "检测到不受支持或会丢失的内容："
                + "、".join(dropped + unsupported)
                + "。如确认接受有损转换，请显式设置 allow_lossy=True。"
            )
        if target_kind == "docx":
            return _convert_markdown_to_docx(
                source_path, target, out_root, profile_obj,
                preserved, changed, dropped, unsupported, notes,
            )
        return _convert_markdown_to_pdf(
            source_path, target, out_root, profile_obj,
            preserved, changed, dropped, unsupported, notes,
            overwrite=overwrite,
        )

    return _convert_docx_to_pdf(source_path, target, out_root, profile_obj)


__all__ = [
    "CONSERVATIVE_NOTE", "CONVERSION_SCHEMA", "CONVERT_TIMEOUT_SECONDS",
    "MARKDOWN_SUFFIXES", "PAGE_SIZES_MM", "PROFILES", "SUPPORTED_TARGETS",
    "ConversionError", "ConversionProfile", "ConversionResult",
    "convert_document", "get_profile", "resolve_output_path",
]

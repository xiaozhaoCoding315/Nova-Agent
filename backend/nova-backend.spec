# PyInstaller spec for the local desktop runtime.
#
# Output: backend/dist/nova-backend/ (onedir). The desktop shell ships this
# directory under resources/backend and spawns ``nova-backend local``.
#
# Build with:
#   backend/.venv/Scripts/pyinstaller backend/nova-backend.spec --noconfirm
#
# The frontend must be built first (``npm run build`` in frontend/), because
# the bundle ships ``frontend/dist`` as ``frontend_dist`` next to the binary.
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).parent
BACKEND = ROOT / "backend"

datas = []
binaries = []
hiddenimports = []


def _collect(package: str) -> None:
    """Collect package data, binaries and submodules; ignore missing extras."""
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
    except Exception as exc:  # noqa: BLE001 - optional dependency
        print(f"skip collecting {package}: {exc}", file=sys.stderr)
        return
    datas.extend(pkg_datas)
    binaries.extend(pkg_binaries)
    hiddenimports.extend(pkg_hidden)


# Embedded PostgreSQL: pgserver keeps a full PostgreSQL installation under
# pgserver/pginstall, including pg_ctl.exe/initdb.exe used by the launcher.
_collect("pgserver")

# Grammars ship compiled parsers loaded through package submodules, which a
# static import analysis cannot see.
for grammar in (
    "tree_sitter_python",
    "tree_sitter_typescript",
    "tree_sitter_go",
    "tree_sitter_java",
    "tree_sitter_rust",
):
    _collect(grammar)

# jieba loads dict.txt at runtime from its package directory.
_collect("jieba")

# python-docx ships templates and part classes imported indirectly; lxml's
# binary wheels carry their own compiled extension next to the package.
_collect("docx")

# uvicorn resolves loops/protocols/lifespan modules by name at startup.
hiddenimports.extend(collect_submodules("uvicorn"))

# Thesis templates are plain JSON files loaded at runtime; ship them next to
# the bundled backend so the desktop build exposes the same template list.
thesis_templates = ROOT / "thesis-templates"
if thesis_templates.is_dir():
    datas.append((str(thesis_templates), "thesis-templates"))
else:
    print(
        "warning: thesis-templates/ is missing; only the generic template will load",
        file=sys.stderr,
    )

frontend_dist = ROOT / "frontend" / "dist"
if frontend_dist.is_dir():
    datas.append((str(frontend_dist), "frontend_dist"))
else:
    print(
        "warning: frontend/dist is missing; the bundle will have no UI",
        file=sys.stderr,
    )

a = Analysis(
    [str(BACKEND / "nova.py")],
    pathex=[str(BACKEND)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["pytest", "pytest_asyncio", "tkinter", "test", "tests"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="nova-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="nova-backend",
)

#!/usr/bin/env python
"""Build the Nova Agent desktop installer.

Steps:
  1. frontend  —— ``npm ci`` (when node_modules is missing) + ``npm run build``
  2. backend   —— PyInstaller onedir bundle ``backend/dist/nova-backend``
  3. installer —— electron-builder NSIS, artifact in ``desktop/out``

Run on Windows for a Windows installer. The backend venv must already contain
PyInstaller and the local requirements:

  python -m venv backend/.venv
  backend/.venv/Scripts/python.exe -m pip install -r backend/requirements.txt \\
      -r backend/requirements-local.txt "pyinstaller>=6.11,<7"

Usage:
  python scripts/build_desktop.py
  python scripts/build_desktop.py --skip-frontend --skip-installer
"""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
BACKEND = ROOT / "backend"
DESKTOP = ROOT / "desktop"
VENV = BACKEND / ".venv"

NPM = shutil.which("npm") or "npm"
NPX = shutil.which("npx") or "npx"


def _run(command: list[str], cwd: Path) -> None:
    print(f"\n$ {' '.join(command)}  (cwd: {cwd})", flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def _venv_pyinstaller() -> Path | None:
    if os.name == "nt":
        candidate = VENV / "Scripts" / "pyinstaller.exe"
    else:
        candidate = VENV / "bin" / "pyinstaller"
    if candidate.is_file():
        return candidate
    found = shutil.which("pyinstaller")
    return Path(found) if found else None


def build_frontend() -> None:
    if not (FRONTEND / "node_modules").is_dir():
        _run([NPM, "ci", "--no-audit", "--no-fund"], FRONTEND)
    _run([NPM, "run", "build"], FRONTEND)
    if not (FRONTEND / "dist" / "index.html").is_file():
        raise SystemExit("frontend build finished but frontend/dist/index.html is missing")


def build_backend() -> None:
    pyinstaller = _venv_pyinstaller()
    if pyinstaller is None:
        raise SystemExit(
            "PyInstaller not found. Create backend/.venv and install the packaging "
            "requirements first (see this script's docstring)."
        )
    if not (FRONTEND / "dist" / "index.html").is_file():
        raise SystemExit("frontend/dist is missing; build the frontend before the backend")
    _run(
        [
            str(pyinstaller),
            "nova-backend.spec",
            "--noconfirm",
            "--distpath",
            "dist",
            "--workpath",
            "build/pyinstaller",
        ],
        BACKEND,
    )
    binary = BACKEND / "dist" / "nova-backend" / (
        "nova-backend.exe" if os.name == "nt" else "nova-backend"
    )
    if not binary.is_file():
        raise SystemExit(f"PyInstaller finished but {binary} is missing")


def build_installer() -> None:
    if not (BACKEND / "dist" / "nova-backend").is_dir():
        raise SystemExit("backend/dist/nova-backend is missing; build the backend first")
    if not (DESKTOP / "node_modules").is_dir():
        _run([NPM, "ci", "--no-audit", "--no-fund"], DESKTOP)
    _run([NPX, "electron-builder", "--win", "nsis", "--x64"], DESKTOP)
    artifacts = sorted(
        (DESKTOP / "out").glob("*.exe"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    if not artifacts:
        raise SystemExit("electron-builder finished but no installer was produced")
    for artifact in artifacts[:1]:
        size_mb = artifact.stat().st_size / (1024 * 1024)
        print(f"\nInstaller: {artifact}  ({size_mb:.1f} MB)")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the Nova Agent desktop installer")
    parser.add_argument("--skip-frontend", action="store_true")
    parser.add_argument("--skip-backend", action="store_true")
    parser.add_argument("--skip-installer", action="store_true")
    args = parser.parse_args()

    if not args.skip_frontend:
        build_frontend()
    if not args.skip_backend:
        build_backend()
    if not args.skip_installer:
        build_installer()
    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

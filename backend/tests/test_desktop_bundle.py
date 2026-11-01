"""Guards for the desktop packaging contract.

The Electron shell and the PyInstaller bundle have to agree on file names and
version numbers; a mismatch only shows up after an installer build, so keep
the cheap assertions here.
"""
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DESKTOP = ROOT / "desktop"
SPEC = ROOT / "backend" / "nova-backend.spec"

pytestmark = pytest.mark.skipif(
    not DESKTOP.is_dir(), reason="desktop shell is not part of this checkout"
)


def _package() -> dict:
    return json.loads((DESKTOP / "package.json").read_text(encoding="utf-8"))


def test_shell_files_include_every_window_entry() -> None:
    files = _package()["build"]["files"]
    for name in ("main.js", "preload.js", "first-run.html", "launch.html"):
        assert name in files


def test_shell_ships_the_pyinstaller_backend() -> None:
    extra = _package()["build"]["extraResources"]
    assert extra == [
        {"from": "../backend/dist/nova-backend", "to": "backend", "filter": ["**/*"]}
    ]


def test_shell_version_matches_backend_version() -> None:
    from app.api.v1.status import VERSION as api_version
    from app.main import VERSION as app_version

    assert _package()["version"] == api_version == app_version


def test_main_process_uses_the_launch_contract() -> None:
    main = (DESKTOP / "main.js").read_text(encoding="utf-8")
    assert "launch.html" in main
    assert "NOVA_PARENT_WATCH" in main
    assert "nova:launch-status" in main


def test_pyinstaller_spec_bundles_frontend_and_pgserver() -> None:
    spec = SPEC.read_text(encoding="utf-8")
    assert "frontend_dist" in spec
    assert "pgserver" in spec
    assert "tree_sitter_python" in spec

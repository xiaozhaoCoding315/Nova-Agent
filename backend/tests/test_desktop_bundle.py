"""Guards for the desktop packaging contract.

The Electron shell and the PyInstaller bundle have to agree on file names and
version numbers; a mismatch only shows up after an installer build, so keep
the cheap assertions here.
"""
import json
import re
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


def test_update_feed_points_at_the_release_assets() -> None:
    """自动更新靠 Release 页上的 latest*.yml 工作。

    地址写死在主进程，所以这里同时校验仓库 slug 与 package.json 的
    publish 配置一致——两者写错任何一处，客户端都只会安静地收不到更新。
    """
    main = (DESKTOP / "main.js").read_text(encoding="utf-8")
    assert "releases/latest/download" in main
    publish = _package()["build"]["publish"]
    assert publish["provider"] == "github"
    assert f"{publish['owner']}/{publish['repo']}" in main


def test_every_platform_ships_an_updatable_target() -> None:
    """electron-updater 只认 nsis / dmg+zip / AppImage+tar.gz。

    只出安装包（比如 mac 只有 dmg）时，客户端能下载却装不了，所以每个
    平台都必须带一个可更新的产物。
    """
    build = _package()["build"]
    for platform, required in (
        ("win", {"nsis"}),
        ("mac", {"dmg", "zip"}),
        ("linux", {"AppImage", "tar.gz"}),
    ):
        assert required <= set(build[platform]["target"]), platform


def test_ci_publishes_the_update_metadata() -> None:
    workflow = (ROOT / ".github" / "workflows" / "desktop.yml").read_text(
        encoding="utf-8"
    )
    # 上传与发布两个 job 都要带上元数据，只补一处仍然没有更新。
    # 只数清单行，注释里提到文件名不算。
    uploads = re.findall(r"^\s+(desktop/out|artifacts/\*\*/)(latest\*\.yml|.*\.blockmap)$",
                         workflow, re.MULTILINE)
    sources = {source.rstrip("/") for source, _ in uploads}
    assert sources == {"desktop/out", "artifacts/**"}, uploads


def test_folder_picker_bridge_is_wired_end_to_end() -> None:
    """本地首次向导的原生选目录：主进程 handler + preload 暴露 + 前端调用。

    三段任何一段缺失，按钮都会安静地不生效（浏览器模式下本来就该隐藏），
    所以在这里一次性对齐三处名字。
    """
    main = (DESKTOP / "main.js").read_text(encoding="utf-8")
    preload = (DESKTOP / "preload.js").read_text(encoding="utf-8")
    dialog = (
        ROOT / "frontend" / "src" / "components" / "LocalSetupDialog.tsx"
    ).read_text(encoding="utf-8")
    assert "ipcMain.handle('nova:pick-directory'" in main
    assert "properties: ['openDirectory'" in main
    assert "ipcRenderer.invoke('nova:pick-directory')" in preload
    assert "window.novaDesktop?.pickDirectory" in dialog

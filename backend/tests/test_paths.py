"""Path and secret-file guard tests."""
import importlib
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.core.security.paths import (
    SecretPathError,
    UnsafePathError,
    is_secret_path,
    normalize_relpath,
    resolve_repo_path,
)
from app.core.tools.base import ToolBusinessError, ToolContext

read_file_mod = importlib.import_module("app.core.tools.read_file")


def test_normalize_rejects_absolute_and_traversal():
    for bad in ("/etc/passwd", "C:/Windows/win.ini", "../escape.py", "app/../../x.py"):
        with pytest.raises(UnsafePathError):
            normalize_relpath(bad)
    assert normalize_relpath("./app//main.py") == "app/main.py"


def test_secret_file_detection():
    for secret in (".env", ".env.local", ".git/config", "id_rsa", "certs/server.pem", ".npmrc"):
        assert is_secret_path(secret), secret
    for allowed in (".env.example", ".gitignore", "app/main.py", "README.md"):
        assert not is_secret_path(allowed), allowed


def test_resolve_blocks_prefix_sibling_and_symlink_style_paths(tmp_path: Path):
    root = tmp_path / "repo"
    sibling = tmp_path / "repo-evil"
    root.mkdir()
    sibling.mkdir()
    (root / "main.py").write_text("print(1)", encoding="utf-8")
    (sibling / "secret.txt").write_text("secret", encoding="utf-8")

    assert resolve_repo_path(root, "main.py") == (root / "main.py").resolve()
    with pytest.raises(UnsafePathError):
        resolve_repo_path(root, "../repo-evil/secret.txt")
    with pytest.raises(UnsafePathError):
        resolve_repo_path(root, str(sibling / "secret.txt"))


def test_resolve_blocks_secret_file(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".env").write_text("API_KEY=secret", encoding="utf-8")

    with pytest.raises(SecretPathError):
        resolve_repo_path(root, ".env")
    assert resolve_repo_path(root, ".env", allow_secret=True).name == ".env"


@pytest.mark.asyncio
async def test_read_file_tool_blocks_secret_and_traversal(monkeypatch, tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".env").write_text("API_KEY=secret", encoding="utf-8")
    (root / "main.py").write_text("print(1)\n", encoding="utf-8")
    monkeypatch.setattr(read_file_mod, "get_repo", AsyncMock(return_value={"root_path": str(root)}))
    ctx = ToolContext(user={"id": 1}, repo_ids=["r1"])

    with pytest.raises(ToolBusinessError, match="密钥"):
        await read_file_mod.read_file({"path": ".env"}, ctx)
    with pytest.raises(ToolBusinessError, match="穿越"):
        await read_file_mod.read_file({"path": "../escape.py"}, ctx)

    result = await read_file_mod.read_file({"path": "main.py"}, ctx)
    assert result["content"].strip() == "print(1)"

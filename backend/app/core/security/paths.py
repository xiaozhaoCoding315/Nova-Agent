"""Repo-scoped path safety.

String prefix checks are not enough on their own: ``D:/repos/a`` is a prefix
of ``D:/repos/ab``. Every agent-visible file operation resolves through this
module so absolute paths, traversal, symlink escapes and secret files are
rejected consistently.
"""
import re
from pathlib import Path, PurePosixPath

_SECRET_DIRS = {".git", ".ssh", ".aws", ".kube", ".gnupg"}
_SECRET_NAMES = {
    ".npmrc", ".pypirc", "credentials.json", "secrets.json",
    "credentials.yaml", "credentials.yml", "secrets.yaml", "secrets.yml",
    "id_rsa", "id_ed25519",
}
_SECRET_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".keystore")
_SAFE_EXAMPLES = (".example", ".sample", ".template", ".dist")


class UnsafePathError(ValueError):
    """Path is absolute, traverses outside the repo, or escapes via symlink."""


class SecretPathError(UnsafePathError):
    """Path points at a credential/secret file."""


def normalize_relpath(path: str) -> str:
    """Return a normalized POSIX-style path relative to the repo root."""
    raw = str(path or "").replace("\\", "/").strip()
    if not raw:
        raise UnsafePathError("路径不能为空")
    if raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
        raise UnsafePathError(f"不允许使用绝对路径：{path}")
    parts = [p for p in raw.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise UnsafePathError(f"不允许路径穿越：{path}")
    if not parts:
        raise UnsafePathError("路径不能为空")
    return "/".join(parts)


def is_secret_path(path: str) -> bool:
    """True for .env / credentials / private keys and similar files."""
    try:
        rel = normalize_relpath(path)
    except UnsafePathError:
        return True
    parts = PurePosixPath(rel).parts
    if any(part in _SECRET_DIRS for part in parts):
        return True

    name = parts[-1].lower()
    if name in _SECRET_NAMES:
        return True
    if name == ".env" or name.startswith(".env."):
        return not name.endswith(_SAFE_EXAMPLES)
    return name.endswith(_SECRET_SUFFIXES)


def resolve_repo_path(root: str | Path, path: str, *, allow_secret: bool = False) -> Path:
    """Resolve ``path`` inside ``root`` or raise ``UnsafePathError``."""
    rel = normalize_relpath(path)
    if not allow_secret and is_secret_path(rel):
        raise SecretPathError(f"拒绝访问密钥/凭据文件：{rel}")

    root_path = Path(root).resolve()
    target = (root_path / PurePosixPath(rel)).resolve()
    if target != root_path and root_path not in target.parents:
        raise UnsafePathError(f"路径越出仓库范围：{path}")
    return target


def try_normalize_relpath(path: str) -> str | None:
    """Best-effort normalize used by validators that skip invalid entries."""
    try:
        return normalize_relpath(path)
    except UnsafePathError:
        return None

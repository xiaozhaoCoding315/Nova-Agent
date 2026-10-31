"""Local desktop configuration. Never import app.config from this module.

The launcher must create the data dir and SECRET_KEY before the Settings
singleton is imported, so this module depends only on the standard library.
"""
import json
import os
import secrets
import sys
from collections.abc import Mapping
from pathlib import Path

CONFIG_VERSION = 1
FILENAME = "nova-config.json"


def default_config_path(
    platform: str | None = None,
    env: Mapping[str, str] | None = None,
) -> Path:
    env = env or os.environ
    override = env.get("NOVA_CONFIG_PATH")
    if override:
        return Path(override)
    plat = platform or sys.platform
    if plat == "win32":
        base = Path(env.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
    elif plat == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(env.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
    return base / "Nova" / FILENAME


def _atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def load_or_create(path: str | Path | None = None) -> dict:
    target = Path(path) if path else default_config_path()
    if target.exists():
        data = json.loads(target.read_text(encoding="utf-8"))
        if int(data.get("version", 0)) != CONFIG_VERSION:
            raise ValueError(f"unsupported nova-config version: {data.get('version')!r}")
        changed = False
        if not data.get("secretKey") or len(str(data["secretKey"])) < 32:
            data["secretKey"] = secrets.token_urlsafe(48)
            changed = True
        if not data.get("dataDir"):
            data["dataDir"] = str(target.parent)
            changed = True
        if "allowInstallDeps" not in data:
            data["allowInstallDeps"] = False
            changed = True
        if changed:
            _atomic_write(target, data)
        return data

    data = {
        "version": CONFIG_VERSION,
        "mode": "local",
        "serverUrl": "",
        "dataDir": str(target.parent),
        "secretKey": secrets.token_urlsafe(48),
        "updateUrl": "",
        "pgBackend": "pgserver",
        "allowInstallDeps": False,
    }
    _atomic_write(target, data)
    return data


def runtime_env(config: dict, *, data_dir: Path | None = None) -> dict[str, str]:
    data = Path(data_dir or config.get("dataDir") or "").expanduser().resolve()
    backend = str(config.get("pgBackend") or "pgserver")
    return {
        "NOVA_MODE": "local",
        "NOVA_DATA_DIR": str(data),
        "SECRET_KEY": str(config["secretKey"]),
        "USER_DATA_DIR": str(data / "users"),
        "REPOS_DIR": str(data / "legacy-repos"),
        "SKILLS_DIR": str(data / "skills"),
        "LOG_DIR": str(data / "logs"),
        "DOWNLOADS_DIR": str(data / "downloads"),
        "MCP_CONFIG_PATH": str(data / "mcp.json"),
        "LOCAL_TMP_DIR": str(data / "tmp"),
        "LOCAL_PG_DATA_DIR": str(data / "pgdata"),
        "LOCAL_PG_BACKEND": backend,
        "LOCAL_PG_BIN_DIR": str(config.get("pgBinDir") or os.environ.get("LOCAL_PG_BIN_DIR") or ""),
        "LOCAL_ALLOW_INSTALL_DEPS": (
            "true" if config.get("allowInstallDeps")
            or os.environ.get("LOCAL_ALLOW_INSTALL_DEPS", "").lower() in ("1", "true", "yes")
            else "false"
        ),
        "EMBEDDINGS_ENABLED": "false",
        "SANDBOX_ENABLED": "false",
        "MCP_ENABLED": "false",
        "AUTO_INIT_DB": "true",
        "JOB_RUNNER_ENABLED": "true",
        "APP_ENV": "local",
    }


def redacted_config(config: dict) -> dict:
    safe = dict(config)
    safe.pop("secretKey", None)
    return safe

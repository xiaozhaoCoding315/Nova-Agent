import json
import os

import pytest

from app.local.config import (
    default_config_path,
    load_or_create,
    redacted_config,
    runtime_env,
)


def test_default_config_path_windows(monkeypatch):
    p = default_config_path(
        platform="win32",
        env={"APPDATA": "C:/Users/alice/AppData/Roaming"},
    )
    assert str(p).replace("\\", "/").endswith("Nova/nova-config.json")


def test_default_config_path_respects_override():
    p = default_config_path(
        platform="win32",
        env={"NOVA_CONFIG_PATH": "D:/Nova/nova-config.json", "APPDATA": "C:/x"},
    )
    assert str(p).replace("\\", "/").endswith("Nova/nova-config.json")


def test_load_or_create_generates_secret_and_data_dir(tmp_path):
    path = tmp_path / "Nova" / "nova-config.json"
    cfg = load_or_create(path)
    assert path.is_file()
    assert cfg["version"] == 1
    assert cfg["mode"] == "local"
    assert cfg["dataDir"] == str(path.parent)
    assert len(cfg["secretKey"]) >= 32
    assert "apiKey" not in json.dumps(cfg)
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["secretKey"] == cfg["secretKey"]


def test_load_or_create_is_stable(tmp_path):
    path = tmp_path / "nova-config.json"
    first = load_or_create(path)
    second = load_or_create(path)
    assert first["secretKey"] == second["secretKey"]


def test_load_or_create_rejects_unknown_version(tmp_path):
    path = tmp_path / "nova-config.json"
    path.write_text(json.dumps({"version": 99}), encoding="utf-8")
    with pytest.raises(ValueError, match="version"):
        load_or_create(path)


def test_runtime_env_contains_no_secret_in_key_names_only(tmp_path):
    cfg = load_or_create(tmp_path / "nova-config.json")
    env = runtime_env(cfg)
    assert env["NOVA_MODE"] == "local"
    assert env["SECRET_KEY"] == cfg["secretKey"]
    assert env["NOVA_DATA_DIR"] == cfg["dataDir"]
    assert env["LOCAL_PG_DATA_DIR"].endswith("pgdata")
    assert env["EMBEDDINGS_ENABLED"] == "false"
    assert env["AUTO_INIT_DB"] == "true"
    assert env["APP_ENV"] == "local"
    assert "ZHIPU_API_KEY" not in env


def test_runtime_env_points_frozen_build_at_bundled_frontend(tmp_path, monkeypatch):
    cfg = load_or_create(tmp_path / "nova-config.json")
    monkeypatch.setattr("app.local.config.sys.frozen", True, raising=False)
    monkeypatch.setattr("app.local.config.sys._MEIPASS", str(tmp_path / "bundle"), raising=False)
    env = runtime_env(cfg)
    assert env["FRONTEND_DIST"].replace("\\", "/").endswith("bundle/frontend_dist")


def test_runtime_env_leaves_frontend_dist_to_source_tree_when_not_frozen(tmp_path, monkeypatch):
    cfg = load_or_create(tmp_path / "nova-config.json")
    monkeypatch.delattr("app.local.config.sys.frozen", raising=False)
    assert "FRONTEND_DIST" not in runtime_env(cfg)


def test_redacted_config_removes_secret(tmp_path):
    cfg = load_or_create(tmp_path / "nova-config.json")
    safe = redacted_config(cfg)
    assert "secretKey" not in safe
    assert safe["mode"] == "local"


@pytest.mark.skipif(os.name == "nt", reason="chmod is a no-op on Windows")
def test_config_file_is_private(tmp_path):
    path = tmp_path / "nova-config.json"
    load_or_create(path)
    assert (path.stat().st_mode & 0o777) == 0o600

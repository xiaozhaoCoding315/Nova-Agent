"""Contract discovery and Gate step generation."""
from app.core.contracts.service import (
    contract_step, contract_step_name, discover_contract, discover_contract_from_root,
    parse_nova_config,
)
from app.core.verify.profiles import detect_profile


def test_discover_contract_auto_detects_source_and_target():
    info = discover_contract({
        "contracts/openapi.yaml": "openapi: 3.1.0",
        "frontend/src/lib/api-schema.d.ts": "export interface paths {}",
    })
    assert info["configured"] is True
    assert info["source"] == "contracts/openapi.yaml"
    assert info["target"] == "frontend/src/lib/api-schema.d.ts"
    assert info["source_exists"] and info["target_exists"]


def test_nova_config_overrides_paths():
    config = "contract:\n  source: api/openapi.json\n  target: web/src/api/schema.d.ts\n"
    assert parse_nova_config(config)["contract"]["source"] == "api/openapi.json"
    info = discover_contract({
        "nova.yaml": config,
        "api/openapi.json": "{}",
        "web/src/api/schema.d.ts": "",
    })
    assert info["from_config"] is True
    assert info["source"] == "api/openapi.json"
    assert info["target"] == "web/src/api/schema.d.ts"


def test_contract_step_uses_openapi_typescript_and_node():
    step = contract_step({"contracts/openapi.json": "{}", "frontend/src/lib/api-schema.d.ts": ""})
    assert step is not None
    assert step["name"] == contract_step_name()
    assert "openapi-typescript" in step["command"]
    assert "node -e" in step["command"]


def test_profile_includes_contract_check_even_without_package_json():
    profile = detect_profile({
        "contracts/openapi.json": "{}",
        "frontend/src/lib/api-schema.d.ts": "",
    })
    assert profile.stack == "node"
    assert any(step.name == "契约检查" and step.image == "node" for step in profile.steps)


def test_contract_missing_target_is_flagged():
    info = discover_contract({"contracts/openapi.json": "{}"})
    assert info["configured"] is True
    assert info["target_exists"] is False


def test_discover_contract_from_root(tmp_path):
    (tmp_path / "contracts").mkdir()
    (tmp_path / "contracts" / "openapi.json").write_text("{}", encoding="utf-8")
    (tmp_path / "web" / "src" / "lib").mkdir(parents=True)
    (tmp_path / "web" / "src" / "lib" / "api-schema.d.ts").write_text("", encoding="utf-8")
    info = discover_contract_from_root(tmp_path)
    assert info["source"] == "contracts/openapi.json"
    assert info["target"] == "web/src/lib/api-schema.d.ts"
    assert info["target_exists"] is True

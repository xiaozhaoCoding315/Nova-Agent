"""The committed OpenAPI contract must match the running FastAPI app."""
import json
from pathlib import Path

from app.main import app

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "contracts" / "openapi.json"


def test_openapi_contract_is_current():
    expected = json.dumps(
        app.openapi(), ensure_ascii=False, indent=2, sort_keys=True
    ) + "\n"
    assert CONTRACT.exists(), "contracts/openapi.json missing; run python -m scripts.export_openapi"
    assert CONTRACT.read_text(encoding="utf-8") == expected


def test_key_endpoints_have_typed_responses():
    spec = app.openapi()
    schemas = spec.get("components", {}).get("schemas", {})
    for name in (
        "ChangeOut", "ChangeListItemOut", "JobOut", "TaskOut",
        "VerifyResultOut", "BrainOut", "ImpactOut", "ReviewOut",
    ):
        assert name in schemas

    for path, method in (
        ("/api/v1/changes", "get"),
        ("/api/v1/changes", "post"),
        ("/api/v1/jobs", "get"),
        ("/api/v1/tasks", "get"),
        ("/api/v1/repos/{repo_id}/brain", "get"),
        ("/api/v1/repos/{repo_id}/impact", "get"),
    ):
        operation = spec["paths"][path][method]
        response = operation["responses"]["200"]["content"]["application/json"]["schema"]
        assert response, f"{method.upper()} {path} has no JSON response schema"

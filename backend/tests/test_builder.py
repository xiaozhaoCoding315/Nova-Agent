"""Builder pure-logic tests: file validation and plan sanitizing."""
import json
from unittest.mock import AsyncMock

import pytest

from app.core.builder import engine
from app.core.builder.engine import _clean_plan, _parse_contract, _finalize_fullstack, validate_files


def test_validate_files_accepts_list_and_dict():
    files = validate_files([
        {"path": "app/main.py", "content": "print(1)"},
        {"path": "README.md", "content": "# hi"},
    ])
    assert set(files) == {"app/main.py", "README.md"}

    as_dict = validate_files({"a.py": "x = 1"})
    assert as_dict == {"a.py": "x = 1"}


def test_validate_files_rejects_traversal_and_empty():
    files = validate_files([
        {"path": "../evil.py", "content": "x"},
        {"path": "/abs.py", "content": "x"},
        {"path": "ok.py", "content": "  "},
        {"path": "fine.py", "content": "print(1)"},
    ])
    assert files == {"fine.py": "print(1)"}


def test_validate_files_caps_count_and_size():
    many = [{"path": f"f{i}.py", "content": "x" * 10} for i in range(50)]
    files = validate_files(many)
    assert len(files) <= 30


def test_clean_plan_sanitizes_lists():
    plan = _clean_plan({
        "summary": "todo app",
        "stack": ["Python", "FastAPI"],
        "structure": [{"path": "app/main.py", "purpose": "entry"}],
        "api": [{"method": "GET", "path": "/items", "description": "list"}],
        "milestones": [{"name": "M1"}],
        "risks": ["sqlite locking"],
        "unexpected": "ignored",
    })
    assert plan["summary"] == "todo app"
    assert plan["stack"] == ["Python", "FastAPI"]
    assert plan["structure"][0]["path"] == "app/main.py"
    assert "unexpected" not in plan


def test_parse_contract_requires_openapi_paths():
    with pytest.raises(ValueError, match="paths"):
        _parse_contract('{"openapi": "3.1.0"}')
    with pytest.raises(ValueError, match="3.x"):
        _parse_contract('{"paths": {}}')
    contract = _parse_contract('{"openapi": "3.1.0", "paths": {"/items": {"get": {}}}}')
    assert "/items" in contract["paths"]


@pytest.mark.asyncio
async def test_finalize_fullstack_adds_generated_frontend(monkeypatch):
    contract = {
        "openapi": "3.1.0",
        "info": {"title": "Demo", "version": "1.0.0"},
        "paths": {"/items": {"get": {"responses": {"200": {"description": "ok"}}}}},
    }
    monkeypatch.setattr(
        engine, "_generate_contract_types",
        AsyncMock(return_value="export interface paths { '/items': unknown }\n"),
    )
    files = await _finalize_fullstack({
        "contracts/openapi.json": json.dumps(contract),
        "app/main.py": "print(1)",
        "frontend/ignored.ts": "ignored",
        "package.json": "{}",
        "nova.yaml": "unexpected: true",
    }, "demo")

    assert "frontend/src/lib/api-schema.d.ts" in files
    assert "frontend/src/app.ts" in files
    assert "tests/test_contract.py" in files
    assert "frontend/src/endpoints.json" in files
    assert "frontend/ignored.ts" not in files
    assert files["package.json"] != "{}"
    assert "source: contracts/openapi.json" in files["nova.yaml"]
    assert json.loads(files["frontend/src/endpoints.json"]) == ["/items"]
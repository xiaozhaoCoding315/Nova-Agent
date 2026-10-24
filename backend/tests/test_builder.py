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

def test_quality_files_are_deterministic():
    from app.core.builder.engine import _quality_files

    plan = {"api": ["POST /api/tasks 创建任务", "GET /api/tasks/{id} 查询任务"]}
    files = _quality_files({"app/main.py": "x"}, plan, "python")
    assert ".github/workflows/ci.yml" in files
    assert "pyproject.toml" in files
    assert "pytest -q" in files[".github/workflows/ci.yml"]
    smoke = files["tests/test_smoke.py"]
    assert '"/api/tasks"' in smoke and '"/api/tasks/{id}"' in smoke
    assert "TestClient" in smoke

    full = _quality_files({"app/main.py": "x", "pyproject.toml": "exists"}, plan, "fullstack")
    assert "pyproject.toml" not in full or full.get("pyproject.toml") == "exists"
    assert "npm run build" in full[".github/workflows/ci.yml"]


def test_smoke_test_falls_back_to_health():
    from app.core.builder.engine import _smoke_test_source

    source = _smoke_test_source([])
    assert '"/health"' in source


@pytest.mark.asyncio
async def test_design_chat_endpoint_streams_and_records(monkeypatch):
    from app.api.v1 import builder as builder_api
    from app.models.schemas import BuilderDesignRequest

    class FakeLLM:
        async def astream_with_tools(self, messages, tools, **kwargs):
            assert messages[0]["role"] == "system"
            assert "项目设计搭档" in messages[0]["content"]
            assert messages[-1]["content"] == "做个博客"
            yield {"type": "content", "content": "给谁用？"}
            yield {"type": "usage", "usage": {"prompt_tokens": 1, "completion_tokens": 2}}
            yield {"type": "finish", "finish_reason": "stop"}

    recorded = []

    async def fake_record(*args, **kwargs):
        recorded.append(kwargs.get("source"))

    async def fake_get_llm(user_id=None, model=None, purpose=None):
        assert purpose == "plan"
        return FakeLLM()

    async def fake_budget(user=None, **kwargs):
        return None

    import app.core.llm.factory as factory_mod
    import app.core.llm.usage as usage_mod
    monkeypatch.setattr(factory_mod, "get_llm", fake_get_llm)
    monkeypatch.setattr(usage_mod, "record_usage", fake_record)
    monkeypatch.setattr(builder_api, "ensure_token_budget", fake_budget)

    req = BuilderDesignRequest(
        messages=[{"role": "user", "content": "做个博客"}], stack="fullstack",
    )
    resp = await builder_api.builder_design_chat(req, user={"id": 1})
    assert resp["reply"] == "给谁用？"
    assert recorded == ["builder"]

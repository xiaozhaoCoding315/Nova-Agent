"""Layered human instructions: precedence, paths scoping and prompt injection."""
import json
from unittest.mock import AsyncMock

import pytest

from app.core.memory import instructions as instructions_mod
from app.core.memory.context import build_system_prompt
from app.core.memory.scope import Scope


def _row(
    id=1, level="user", scope_type="global", scope_id="", name="习惯",
    content="先写测试", paths=None, enabled=True, priority=100,
):
    return (
        id, level, scope_type, scope_id, name, content,
        paths if paths is not None else [], enabled, priority,
    )


def test_parse_frontmatter_extracts_paths():
    paths, body = instructions_mod.parse_frontmatter(
        "---\npaths: backend/**, docs/*.md\n---\n只改后端时先跑 pytest。"
    )

    assert paths == ["backend/**", "docs/*.md"]
    assert body == "只改后端时先跑 pytest。"


def test_parse_frontmatter_supports_yaml_list_and_plain_body():
    paths, body = instructions_mod.parse_frontmatter(
        "---\npaths:\n  - app/**\n  - tests/**\n---\n内容"
    )
    assert paths == ["app/**", "tests/**"]
    assert body == "内容"

    paths, body = instructions_mod.parse_frontmatter("没有 frontmatter")
    assert paths == []
    assert body == "没有 frontmatter"


def test_validate_rejects_unsafe_paths_and_bad_scope():
    with pytest.raises(ValueError, match="路径"):
        instructions_mod.validate_payload({
            "level": "user", "content": "x", "paths": ["../etc/passwd"],
        })
    with pytest.raises(ValueError, match="scope_id"):
        instructions_mod.validate_payload({
            "level": "project", "scope_type": "repo", "scope_id": "", "content": "x",
        })
    with pytest.raises(ValueError, match="组织"):
        instructions_mod.validate_payload({
            "level": "org", "scope_type": "dev", "content": "x",
        })


def test_validate_defaults_user_instructions_to_global_scope():
    cleaned = instructions_mod.validate_payload({"content": "永远先跑测试"})

    assert cleaned["level"] == "user"
    assert cleaned["scope_type"] == "global"
    assert cleaned["scope_id"] == ""
    assert cleaned["name"]


def test_validate_merges_frontmatter_paths_into_row():
    cleaned = instructions_mod.validate_payload({
        "level": "project", "scope_type": "repo", "scope_id": "r1",
        "content": "---\npaths: app/**\n---\n改 app 前先读规则",
    })

    assert cleaned["paths"] == ["app/**"]
    assert "paths:" not in cleaned["content"]
    assert cleaned["content"] == "改 app 前先读规则"


@pytest.mark.asyncio
async def test_for_turn_orders_org_user_project_and_filters_scope(monkeypatch):
    rows = [
        _row(1, "project", "repo", "r1", "仓库规则", "仓库内容"),
        _row(2, "user", "global", "", "用户习惯", "用户内容"),
        _row(3, "org", "global", "", "组织策略", "组织内容"),
        _row(4, "project", "repo", "r2", "别的仓库", "不应出现"),
        _row(5, "user", "global", "", "停用", "不应出现", enabled=False),
        _row(6, "user", "global", "", "路径规则", "路径内容", paths=["app/**"]),
    ]
    monkeypatch.setattr(
        instructions_mod, "query", AsyncMock(return_value=rows),
    )

    prompt_rows, path_rows = await instructions_mod.for_turn(
        7, [Scope("global", ""), Scope("repo", "r1")],
    )

    assert [item["name"] for item in prompt_rows] == [
        "组织策略", "用户习惯", "仓库规则",
    ]
    assert [item["name"] for item in path_rows] == ["路径规则"]


def test_format_block_labels_layers_and_warns_about_precedence():
    block = instructions_mod.format_block([
        {"level": "org", "name": "组织策略", "content": "不得自动合并"},
        {"level": "user", "name": "用户习惯", "content": "先写测试"},
    ])

    assert "## 人工指令" in block
    assert "组织策略" in block
    assert "用户习惯" in block
    assert "不得覆盖安全策略" in block
    assert block.index("组织策略") < block.index("用户习惯")


def test_match_path_block_only_returns_matching_instructions():
    rows = [
        {"id": 1, "name": "后端", "content": "后端规则", "paths": ["backend/**"]},
        {"id": 2, "name": "文档", "content": "文档规则", "paths": ["docs/*.md"]},
    ]

    block = instructions_mod.match_path_block(
        rows, ["backend/app/main.py"], set(),
    )
    assert "后端规则" in block
    assert "文档规则" not in block

    block_again = instructions_mod.match_path_block(
        rows, ["backend/app/main.py"], {1},
    )
    assert block_again == ""


def test_paths_from_tool_args_handles_files_and_paths():
    paths = instructions_mod.paths_from_tool_args({
        "path": "app/main.py",
        "files": [{"path": "app/a.py"}, "app/b.py"],
        "paths": ["tests/test_a.py"],
    })

    assert paths == [
        "app/main.py", "app/a.py", "app/b.py", "tests/test_a.py",
    ]


def test_system_prompt_injects_instructions_before_facts():
    sections: dict[str, str] = {}
    prompt = build_system_prompt(
        [], ["偏好中文"], instructions=[
            {"level": "user", "name": "习惯", "content": "先写测试"},
        ],
        sections=sections,
    )

    assert "先写测试" in prompt
    assert "## 人工指令" in prompt
    assert prompt.index("人工指令") < prompt.index("用户长期偏好")
    assert "instructions" in sections


@pytest.mark.asyncio
async def test_create_instruction_serializes_paths(monkeypatch):
    execute = AsyncMock(return_value=[_row(9)])
    monkeypatch.setattr(instructions_mod, "execute", execute)
    monkeypatch.setattr(instructions_mod, "get_instruction", AsyncMock(return_value={"id": 9}))

    result = await instructions_mod.create_instruction(7, {
        "level": "project", "scope_type": "repo", "scope_id": "r1",
        "content": "规则", "paths": ["app/**"],
    })

    sql, params = execute.await_args.args
    assert "INSERT INTO user_instructions" in sql
    assert json.loads(params[6]) == ["app/**"]
    assert result == {"id": 9}


@pytest.mark.asyncio
async def test_update_instruction_requires_owner(monkeypatch):
    monkeypatch.setattr(
        instructions_mod, "get_instruction", AsyncMock(return_value=None),
    )
    monkeypatch.setattr(instructions_mod, "execute", AsyncMock())

    with pytest.raises(instructions_mod.InstructionNotFound):
        await instructions_mod.update_instruction(7, 3, {"content": "x"})

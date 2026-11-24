"""User memory policy: defaults, scope overrides and blocked content."""
import json
from unittest.mock import AsyncMock

import pytest

from app.core.memory import policy as policy_mod
from app.core.memory.scope import Scope


def test_default_policy_allows_automatic_memory():
    policy = policy_mod.DEFAULT_POLICY

    assert policy.auto_memory is True
    assert policy.retention_days == 90
    assert policy_mod.scope_allowed(policy, Scope("repo", "r1")) is True
    assert policy_mod.allows_fact(policy, "偏好中文回答", "preference") is True


def test_scope_override_can_disable_one_repo():
    policy = policy_mod.MemoryPolicy(
        scope_overrides={"repo:r1": {"auto_memory": False}},
    )

    assert policy_mod.scope_allowed(policy, Scope("repo", "r1")) is False
    assert policy_mod.scope_allowed(policy, Scope("repo", "r2")) is True
    assert policy_mod.scope_allowed(policy, Scope("dev", "")) is True


def test_master_switch_disables_every_scope():
    policy = policy_mod.MemoryPolicy(auto_memory=False)

    assert policy_mod.scope_allowed(policy, Scope("global", "")) is False
    assert policy_mod.scope_allowed(policy, Scope("dev", "")) is False


def test_blocked_category_and_keyword_stop_learning():
    policy = policy_mod.MemoryPolicy(
        blocked_categories=("project",),
        blocked_keywords=("密码", "token"),
    )

    assert policy_mod.allows_fact(policy, "项目代号 Nova", "project") is False
    assert policy_mod.allows_fact(policy, "数据库密码是 x", "fact") is False
    assert policy_mod.allows_fact(policy, "喜欢用 pytest", "preference") is True


@pytest.mark.asyncio
async def test_get_policy_parses_stored_row(monkeypatch):
    rows = [(
        False, 30, "global",
        ["project"], ["secret"], {"repo:r1": {"auto_memory": False}},
    )]
    monkeypatch.setattr(policy_mod, "query", AsyncMock(return_value=rows))

    policy = await policy_mod.get_policy(7)

    assert policy.auto_memory is False
    assert policy.retention_days == 30
    assert policy.default_scope == "global"
    assert policy.blocked_categories == ("project",)
    assert policy.blocked_keywords == ("secret",)
    assert policy.scope_overrides == {"repo:r1": {"auto_memory": False}}


@pytest.mark.asyncio
async def test_get_policy_defaults_when_no_row(monkeypatch):
    monkeypatch.setattr(policy_mod, "query", AsyncMock(return_value=[]))

    assert await policy_mod.get_policy(7) == policy_mod.DEFAULT_POLICY


@pytest.mark.asyncio
async def test_update_policy_upserts_serialized_lists(monkeypatch):
    execute = AsyncMock()
    stored = [(
        True, 14, "dev", ["correction"], ["secret"], {},
    )]
    monkeypatch.setattr(policy_mod, "execute", execute)
    monkeypatch.setattr(policy_mod, "query", AsyncMock(return_value=stored))

    result = await policy_mod.update_policy(7, {
        "retention_days": 14,
        "blocked_categories": ["correction"],
        "blocked_keywords": ["secret", " "],
    })

    sql, params = execute.await_args.args
    assert "ON CONFLICT (user_id) DO UPDATE" in sql
    assert params == (7, 14, json.dumps(["correction"]), json.dumps(["secret"]))
    assert result.blocked_categories == ("correction",)


@pytest.mark.parametrize("values, message", [
    ({"retention_days": 0}, "保留天数"),
    ({"default_scope": "repo"}, "默认作用域"),
    ({"blocked_categories": ["nope"]}, "未知记忆类别"),
    ({"blocked_keywords": ["x" * 51]}, "关键词"),
])
def test_validate_update_rejects_bad_input(values, message):
    with pytest.raises(ValueError, match=message):
        policy_mod.validate_update(values)

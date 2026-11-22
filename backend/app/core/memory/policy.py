"""Per-user memory policy: automatic learning, retention and scope overrides."""
from __future__ import annotations

from dataclasses import dataclass, field

from app.core.memory import scope as scope_mod
from app.db import execute, query

MEMORY_CATEGORIES = ("fact", "preference", "project", "decision", "correction")
DEFAULT_RETENTION_DAYS = 90
MAX_RETENTION_DAYS = 3650
MAX_BLOCKED_KEYWORDS = 50
MAX_KEYWORD_CHARS = 50


@dataclass(frozen=True)
class MemoryPolicy:
    auto_memory: bool = True
    retention_days: int = DEFAULT_RETENTION_DAYS
    default_scope: str = scope_mod.DEV
    blocked_categories: tuple[str, ...] = field(default_factory=tuple)
    blocked_keywords: tuple[str, ...] = field(default_factory=tuple)
    scope_overrides: dict = field(default_factory=dict)


DEFAULT_POLICY = MemoryPolicy()


def scope_key(scope: scope_mod.Scope) -> str:
    return f"{scope.type}:{scope.id}"


def scope_allowed(policy: MemoryPolicy, scope: scope_mod.Scope) -> bool:
    """Whether automatic memory may read/write this scope."""
    if not policy.auto_memory:
        return False
    override = policy.scope_overrides.get(scope_key(scope))
    if isinstance(override, dict) and override.get("auto_memory") is False:
        return False
    return True


def allows_fact(policy: MemoryPolicy, content: str, category: str) -> bool:
    """Blocked categories/keywords apply to learning and to injection."""
    if category in policy.blocked_categories:
        return False
    text = (content or "").lower()
    return not any(word and word.lower() in text for word in policy.blocked_keywords)


def _as_str_tuple(value) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value if str(item).strip())


def _as_dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _policy_from_row(row) -> MemoryPolicy:
    if not row:
        return DEFAULT_POLICY
    return MemoryPolicy(
        auto_memory=bool(row[0]),
        retention_days=int(row[1] or DEFAULT_RETENTION_DAYS),
        default_scope=str(row[2] or scope_mod.DEV),
        blocked_categories=_as_str_tuple(row[3]),
        blocked_keywords=_as_str_tuple(row[4]),
        scope_overrides=_as_dict(row[5]),
    )


async def get_policy(user_id: int) -> MemoryPolicy:
    rows = await query(
        "SELECT auto_memory, retention_days, default_scope, blocked_categories, "
        "blocked_keywords, scope_overrides FROM user_memory_settings "
        "WHERE user_id = %s",
        (user_id,),
    )
    return _policy_from_row(rows[0]) if rows else DEFAULT_POLICY


def validate_update(values: dict) -> dict:
    """Normalise a partial settings update; raises ``ValueError`` on bad input."""
    import json

    cleaned: dict = {}
    if "auto_memory" in values:
        cleaned["auto_memory"] = bool(values["auto_memory"])
    if "retention_days" in values:
        try:
            days = int(values["retention_days"])
        except (TypeError, ValueError):
            raise ValueError("保留天数必须是整数")
        if not 1 <= days <= MAX_RETENTION_DAYS:
            raise ValueError(f"保留天数需在 1–{MAX_RETENTION_DAYS} 之间")
        cleaned["retention_days"] = days
    if "default_scope" in values:
        kind = str(values["default_scope"] or "").strip().lower()
        if kind not in (scope_mod.GLOBAL, scope_mod.DEV):
            raise ValueError("默认作用域只能是 global 或 dev")
        cleaned["default_scope"] = kind
    if "blocked_categories" in values:
        items = [str(item) for item in (values["blocked_categories"] or [])]
        invalid = [item for item in items if item not in MEMORY_CATEGORIES]
        if invalid:
            raise ValueError(f"未知记忆类别：{', '.join(sorted(set(invalid)))}")
        cleaned["blocked_categories"] = json.dumps(
            list(dict.fromkeys(items)), ensure_ascii=False
        )
    if "blocked_keywords" in values:
        raw = values["blocked_keywords"] or []
        items = [str(item).strip() for item in raw if str(item).strip()]
        if len(items) > MAX_BLOCKED_KEYWORDS:
            raise ValueError(f"屏蔽关键词最多 {MAX_BLOCKED_KEYWORDS} 个")
        too_long = [item for item in items if len(item) > MAX_KEYWORD_CHARS]
        if too_long:
            raise ValueError(f"单个关键词不能超过 {MAX_KEYWORD_CHARS} 字")
        cleaned["blocked_keywords"] = json.dumps(
            list(dict.fromkeys(items)), ensure_ascii=False
        )
    if "scope_overrides" in values:
        overrides = values["scope_overrides"] or {}
        if not isinstance(overrides, dict):
            raise ValueError("作用域覆盖必须是对象")
        normalised: dict[str, dict] = {}
        for key, item in overrides.items():
            name = str(key).strip()
            if not name:
                continue
            if not isinstance(item, dict):
                raise ValueError(f"作用域覆盖 {name} 必须是对象")
            entry: dict = {}
            if "auto_memory" in item:
                entry["auto_memory"] = bool(item["auto_memory"])
            normalised[name] = entry
        cleaned["scope_overrides"] = json.dumps(normalised, ensure_ascii=False)
    return cleaned


async def update_policy(user_id: int, values: dict) -> MemoryPolicy:
    cleaned = validate_update(values)
    if not cleaned:
        return await get_policy(user_id)
    columns = ", ".join(cleaned)
    placeholders = ", ".join(["%s"] * len(cleaned))
    updates = ", ".join(f"{name} = EXCLUDED.{name}" for name in cleaned)
    await execute(
        f"INSERT INTO user_memory_settings (user_id, {columns}) "
        f"VALUES (%s, {placeholders}) "
        f"ON CONFLICT (user_id) DO UPDATE SET {updates}, updated_at = now()",
        (user_id, *cleaned.values()),
    )
    return await get_policy(user_id)


def to_dict(policy: MemoryPolicy) -> dict:
    return {
        "auto_memory": policy.auto_memory,
        "retention_days": policy.retention_days,
        "default_scope": policy.default_scope,
        "blocked_categories": list(policy.blocked_categories),
        "blocked_keywords": list(policy.blocked_keywords),
        "scope_overrides": dict(policy.scope_overrides),
    }

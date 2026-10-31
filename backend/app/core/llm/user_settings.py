"""Per-user LLM credentials, encrypted at rest.

A user can save one credential per provider. Exactly one row is the default
(partial unique index); the chat composer may override provider/model for a
single session without changing the default.
"""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings
from app.core.llm.providers import (
    get_provider, provider_list, resolve_base_url,
)
from app.db import execute, query

MAX_MODEL_LENGTH = 120
REASONING_EFFORTS = {"", "low", "medium", "high"}
MAX_CONTEXT_WINDOW = 10_000_000

_SELECT = (
    "SELECT provider, base_url, model, api_key_enc, context_window, "
    "reasoning_effort, is_default, updated_at FROM user_llm_providers"
)


def provider_presets() -> list[dict]:
    """Backward-compatible alias for the old settings endpoint."""
    return provider_list()


def provider_by_id(provider_id: str):
    return get_provider(provider_id)


def _fernet() -> Fernet:
    digest = hashlib.sha256(settings.secret_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_key(api_key: str) -> str:
    return _fernet().encrypt(api_key.encode("utf-8")).decode("ascii")


def decrypt_key(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        raise ValueError("API Key 无法解密，请重新保存")


def _clean_model(model: str) -> str:
    value = (model or "").strip()
    if not value:
        raise ValueError("请选择或填写模型名称")
    if len(value) > MAX_MODEL_LENGTH:
        raise ValueError(f"模型名称不能超过 {MAX_MODEL_LENGTH} 个字符")
    return value


def clean_context_window(value: int | None) -> int | None:
    if value is None or int(value) <= 0:
        return None
    value = int(value)
    if value < 2048 or value > MAX_CONTEXT_WINDOW:
        raise ValueError("上下文窗口需在 2048 - 10,000,000 tokens 之间")
    return value


def clean_reasoning_effort(value: str | None) -> str:
    effort = (value or "").strip().lower()
    if effort not in REASONING_EFFORTS:
        raise ValueError("推理强度只能是 low / medium / high 或留空")
    return effort


def _row_to_config(row) -> dict:
    provider, base_url, model, encrypted, context_window, effort, is_default, updated_at = row
    api_key = ""
    key_error = ""
    try:
        api_key = decrypt_key(encrypted) if encrypted else ""
    except ValueError as exc:
        key_error = str(exc)
    return {
        "provider": provider,
        "base_url": base_url,
        "model": model,
        "api_key": api_key,
        "key_hint": f"••••{api_key[-4:]}" if len(api_key) >= 8 else ("••••" if api_key else ""),
        "key_error": key_error,
        "context_window": int(context_window) if context_window else None,
        "reasoning_effort": effort or "",
        "is_default": bool(is_default),
        "updated_at": updated_at,
    }


async def list_user_configs(user_id: int) -> list[dict]:
    rows = await query(
        f"{_SELECT} WHERE user_id = %s ORDER BY is_default DESC, updated_at DESC",
        (user_id,),
    )
    return [_row_to_config(row) for row in rows]


async def get_user_config(user_id: int, provider: str | None = None) -> dict | None:
    if provider:
        rows = await query(
            f"{_SELECT} WHERE user_id = %s AND provider = %s LIMIT 1",
            (user_id, provider),
        )
    else:
        rows = await query(
            f"{_SELECT} WHERE user_id = %s ORDER BY is_default DESC, updated_at DESC LIMIT 1",
            (user_id,),
        )
    return _row_to_config(rows[0]) if rows else None


async def _raw_key(user_id: int, provider: str) -> str:
    rows = await query(
        "SELECT api_key_enc FROM user_llm_providers WHERE user_id = %s AND provider = %s",
        (user_id, provider),
    )
    if not rows or not rows[0][0]:
        return ""
    # The stored value is ciphertext; save_user_config re-encrypts whatever it
    # receives, so decrypt here to keep a retained key from being wrapped twice.
    return decrypt_key(rows[0][0])


async def _has_default(user_id: int) -> bool:
    rows = await query(
        "SELECT 1 FROM user_llm_providers WHERE user_id = %s AND is_default LIMIT 1",
        (user_id,),
    )
    return bool(rows)


async def save_user_config(
    user_id: int,
    *,
    provider: str,
    model: str,
    base_url: str | None = None,
    api_key: str | None = None,
    context_window: int | None = None,
    reasoning_effort: str | None = None,
    is_default: bool = False,
) -> dict:
    spec = get_provider(provider)
    if not spec:
        raise ValueError("不支持的模型服务商")

    clean_base = resolve_base_url(spec, base_url)
    clean_model = _clean_model(model)

    key = (api_key or "").strip()
    if not key:
        key = await _raw_key(user_id, spec.id)
    if not key and spec.id != "ollama":
        raise ValueError("请填写 API Key")
    if len(key) > 4000:
        raise ValueError("API Key 过长")

    encrypted = encrypt_key(key) if key else ""
    make_default = bool(is_default) or not await _has_default(user_id)

    await execute(
        """
        INSERT INTO user_llm_providers
            (user_id, provider, base_url, model, api_key_enc,
             context_window, reasoning_effort, is_default, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, FALSE, now())
        ON CONFLICT (user_id, provider) DO UPDATE SET
            base_url = EXCLUDED.base_url,
            model = EXCLUDED.model,
            api_key_enc = EXCLUDED.api_key_enc,
            context_window = EXCLUDED.context_window,
            reasoning_effort = EXCLUDED.reasoning_effort,
            updated_at = now()
        """,
        (
            user_id, spec.id, clean_base, clean_model, encrypted,
            clean_context_window(context_window),
            clean_reasoning_effort(reasoning_effort),
        ),
    )
    if make_default:
        # Two statements on purpose: the partial unique index checks per row,
        # so flipping several rows in one UPDATE can fail transiently.
        await execute(
            "UPDATE user_llm_providers SET is_default = FALSE WHERE user_id = %s",
            (user_id,),
        )
        await execute(
            "UPDATE user_llm_providers SET is_default = TRUE "
            "WHERE user_id = %s AND provider = %s",
            (user_id, spec.id),
        )
    saved = await get_user_config(user_id, spec.id)
    if saved is None:
        raise RuntimeError("保存模型配置失败")
    return saved


async def set_default_provider(user_id: int, provider: str) -> dict | None:
    if not await get_user_config(user_id, provider):
        return None
    await execute(
        "UPDATE user_llm_providers SET is_default = FALSE WHERE user_id = %s",
        (user_id,),
    )
    await execute(
        "UPDATE user_llm_providers SET is_default = TRUE "
        "WHERE user_id = %s AND provider = %s",
        (user_id, provider),
    )
    return await get_user_config(user_id, provider)


async def delete_user_config(user_id: int, provider: str | None = None) -> bool:
    if provider:
        rows = await execute(
            "DELETE FROM user_llm_providers WHERE user_id = %s AND provider = %s "
            "RETURNING is_default",
            (user_id, provider),
        )
        if not rows:
            return False
        if rows[0][0]:
            await execute(
                "UPDATE user_llm_providers SET is_default = TRUE "
                "WHERE user_id = %s AND provider = ("
                "  SELECT provider FROM user_llm_providers WHERE user_id = %s "
                "  ORDER BY updated_at DESC LIMIT 1)",
                (user_id, user_id),
            )
        return True
    rows = await execute(
        "DELETE FROM user_llm_providers WHERE user_id = %s RETURNING user_id",
        (user_id,),
    )
    return bool(rows)

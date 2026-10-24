"""Per-user LLM credentials, encrypted at rest.

Users can point Nova at any OpenAI-compatible endpoint. Keys are encrypted
with a key derived from ``SECRET_KEY`` and are never returned by the API.
"""
import base64
import hashlib
from urllib.parse import urlparse

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings
from app.db import execute, query

MAX_MODEL_LENGTH = 120
BLOCKED_HOSTS = {"169.254.169.254", "metadata.google.internal"}


def provider_presets() -> list[dict]:
    return [
        {
            "id": "dashscope",
            "label": "阿里云百炼 / DashScope",
            "base_url": settings.dashscope_base_url,
            "models": ["qwen3.8-max", "qwen3.8-flash", "deepseek-v4-flash-0731"],
        },
        {
            "id": "deepseek",
            "label": "DeepSeek",
            "base_url": "https://api.deepseek.com/v1",
            "models": ["deepseek-chat", "deepseek-reasoner"],
        },
        {
            "id": "openai",
            "label": "OpenAI / 兼容网关",
            "base_url": "https://api.openai.com/v1",
            "models": ["gpt-4o", "gpt-4o-mini"],
        },
        {
            "id": "custom",
            "label": "自定义 OpenAI 兼容端点",
            "base_url": "",
            "models": [],
        },
    ]


def provider_by_id(provider_id: str) -> dict | None:
    return next((item for item in provider_presets() if item["id"] == provider_id), None)


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


def _clean_base_url(provider: dict, base_url: str | None) -> str:
    value = (base_url or provider.get("base_url") or "").strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Base URL 必须是 http(s) 地址")
    if parsed.hostname.lower() in BLOCKED_HOSTS:
        raise ValueError("不允许使用该地址")
    return value


def _clean_model(model: str) -> str:
    value = (model or "").strip()
    if not value:
        raise ValueError("请选择或填写模型名称")
    if len(value) > MAX_MODEL_LENGTH:
        raise ValueError(f"模型名称不能超过 {MAX_MODEL_LENGTH} 个字符")
    return value


async def get_user_config(user_id: int) -> dict | None:
    rows = await query(
        "SELECT provider, base_url, model, api_key_enc, updated_at "
        "FROM user_llm_settings WHERE user_id = %s",
        (user_id,),
    )
    if not rows:
        return None
    provider, base_url, model, encrypted, updated_at = rows[0]
    api_key = ""
    key_error = ""
    try:
        api_key = decrypt_key(encrypted)
    except ValueError as exc:
        key_error = str(exc)
    return {
        "provider": provider,
        "base_url": base_url,
        "model": model,
        "api_key": api_key,
        "key_hint": f"••••{api_key[-4:]}" if len(api_key) >= 8 else ("••••" if api_key else ""),
        "key_error": key_error,
        "updated_at": updated_at,
    }


async def save_user_config(
    user_id: int,
    *,
    provider: str,
    model: str,
    base_url: str | None = None,
    api_key: str | None = None,
) -> dict:
    preset = provider_by_id(provider)
    if not preset:
        raise ValueError("不支持的模型服务商")

    clean_base = _clean_base_url(preset, base_url)
    clean_model = _clean_model(model)

    key = (api_key or "").strip()
    if not key:
        existing = await get_user_config(user_id)
        key = existing["api_key"] if existing else ""
    if not key:
        raise ValueError("请填写 API Key")
    if len(key) > 4000:
        raise ValueError("API Key 过长")

    await execute(
        """
        INSERT INTO user_llm_settings (user_id, provider, base_url, model, api_key_enc, updated_at)
        VALUES (%s, %s, %s, %s, %s, now())
        ON CONFLICT (user_id) DO UPDATE SET
            provider = EXCLUDED.provider,
            base_url = EXCLUDED.base_url,
            model = EXCLUDED.model,
            api_key_enc = EXCLUDED.api_key_enc,
            updated_at = now()
        """,
        (user_id, provider, clean_base, clean_model, encrypt_key(key)),
    )
    saved = await get_user_config(user_id)
    if saved is None:
        raise RuntimeError("保存模型配置失败")
    return saved


async def delete_user_config(user_id: int) -> bool:
    rows = await execute(
        "DELETE FROM user_llm_settings WHERE user_id = %s RETURNING user_id",
        (user_id,),
    )
    return bool(rows)

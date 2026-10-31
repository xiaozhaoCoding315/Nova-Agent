"""Static catalog of supported model providers.

Preset base URLs are server-controlled: a client-supplied base_url is ignored
for every provider except ``custom`` and ``ollama``. This prevents a saved
credential from being redirected to an arbitrary host.
"""
from dataclasses import dataclass
from urllib.parse import urlparse

from app.config import settings

BLOCKED_HOSTS = {"169.254.169.254", "metadata.google.internal"}


@dataclass(frozen=True)
class ProviderSpec:
    id: str
    label: str
    group: str                    # domestic | international | aggregator | local
    kind: str                     # openai | anthropic
    base_url: str
    default_model: str
    models: tuple[str, ...] = ()
    docs_url: str = ""
    free_tier: bool = False
    supports_tools: bool = True
    supports_reasoning: bool = False
    supports_temperature: bool = True
    context_window: int = 131_072
    base_url_locked: bool = True
    env_key: str = ""
    icon: str = ""
    base_url_setting: str = ""    # read the actual URL from Settings at runtime

    def public(self) -> dict:
        base_url = self.base_url
        if self.base_url_setting:
            base_url = str(getattr(settings, self.base_url_setting, base_url) or base_url)
        return {
            "id": self.id,
            "label": self.label,
            "group": self.group,
            "kind": self.kind,
            "base_url": base_url,
            "models": list(self.models),
            "docs_url": self.docs_url,
            "free_tier": self.free_tier,
            "supports_tools": self.supports_tools,
            "supports_reasoning": self.supports_reasoning,
            "supports_temperature": self.supports_temperature,
            "context_window": self.context_window,
            "base_url_locked": self.base_url_locked,
            "env_key": self.env_key,
            "icon": self.icon,
        }


PROVIDERS: tuple[ProviderSpec, ...] = (
    ProviderSpec(
        id="zhipu", label="智谱 GLM", group="domestic", kind="openai",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        default_model="glm-4.7-flash",
        models=("glm-4.7-flash", "glm-4.6", "glm-4.5-air"),
        docs_url="https://open.bigmodel.cn/dev/api",
        free_tier=True, supports_reasoning=True, context_window=131_072,
        env_key="ZHIPU_API_KEY", icon="zhipu",
        base_url_setting="zhipu_base_url",
    ),
    ProviderSpec(
        id="dashscope", label="阿里云百炼 / DashScope", group="domestic", kind="openai",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        default_model="qwen3.8-max",
        models=("qwen3.8-max", "qwen3.8-flash", "qwen3-coder-plus"),
        docs_url="https://help.aliyun.com/zh/model-studio/",
        supports_reasoning=True, context_window=131_072,
        env_key="DASHSCOPE_API_KEY", icon="qwen",
        base_url_setting="dashscope_base_url",
    ),
    ProviderSpec(
        id="deepseek", label="DeepSeek", group="domestic", kind="openai",
        base_url="https://api.deepseek.com/v1",
        default_model="deepseek-chat",
        models=("deepseek-chat", "deepseek-reasoner"),
        docs_url="https://api-docs.deepseek.com/",
        supports_reasoning=True, context_window=131_072,
        env_key="DEEPSEEK_API_KEY", icon="deepseek",
    ),
    ProviderSpec(
        id="moonshot", label="月之暗面 Kimi", group="domestic", kind="openai",
        base_url="https://api.moonshot.cn/v1",
        default_model="kimi-k2",
        models=("kimi-k2", "kimi-k2-0905-preview", "moonshot-v1-128k"),
        docs_url="https://platform.moonshot.cn/docs/",
        supports_reasoning=True, context_window=262_144, icon="moonshot",
    ),
    ProviderSpec(
        id="minimax", label="MiniMax", group="domestic", kind="openai",
        base_url="https://api.minimax.chat/v1",
        default_model="MiniMax-M2",
        models=("MiniMax-M2", "MiniMax-Text-01"),
        docs_url="https://platform.minimaxi.com/document/",
        supports_reasoning=True, context_window=204_800, icon="minimax",
    ),
    ProviderSpec(
        id="siliconflow", label="硅基流动 SiliconFlow", group="domestic", kind="openai",
        base_url="https://api.siliconflow.cn/v1",
        default_model="deepseek-ai/DeepSeek-V3",
        models=(
            "deepseek-ai/DeepSeek-V3",
            "Qwen/Qwen3-Coder-480B-A35B-Instruct",
        ),
        docs_url="https://docs.siliconflow.cn/",
        supports_reasoning=True, context_window=131_072, icon="siliconcloud",
    ),
    ProviderSpec(
        id="volcengine", label="火山方舟 / 豆包", group="domestic", kind="openai",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        default_model="",
        models=(),
        docs_url="https://www.volcengine.com/docs/82379",
        supports_reasoning=True, context_window=131_072, icon="volcengine",
    ),
    ProviderSpec(
        id="openai", label="OpenAI", group="international", kind="openai",
        base_url="https://api.openai.com/v1",
        default_model="gpt-4o",
        models=("gpt-4o", "gpt-4o-mini", "o3-mini"),
        docs_url="https://platform.openai.com/docs/",
        supports_reasoning=True, context_window=128_000,
        env_key="OPENAI_API_KEY", icon="openai",
    ),
    ProviderSpec(
        id="anthropic", label="Anthropic Claude", group="international", kind="anthropic",
        base_url="https://api.anthropic.com",
        default_model="claude-sonnet-5-5",
        models=("claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-5-5"),
        docs_url="https://docs.anthropic.com/",
        supports_reasoning=True, context_window=200_000,
        env_key="ANTHROPIC_API_KEY", icon="anthropic",
        base_url_setting="anthropic_base_url",
    ),
    ProviderSpec(
        id="gemini", label="Google Gemini", group="international", kind="openai",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        default_model="gemini-2.5-pro",
        models=("gemini-2.5-pro", "gemini-2.5-flash"),
        docs_url="https://ai.google.dev/gemini-api/docs",
        supports_reasoning=True, context_window=1_048_576, icon="gemini",
    ),
    ProviderSpec(
        id="xai", label="xAI Grok", group="international", kind="openai",
        base_url="https://api.x.ai/v1",
        default_model="grok-4",
        models=("grok-4", "grok-3-mini"),
        docs_url="https://docs.x.ai/",
        supports_reasoning=True, context_window=256_000, icon="xai",
    ),
    ProviderSpec(
        id="mistral", label="Mistral AI", group="international", kind="openai",
        base_url="https://api.mistral.ai/v1",
        default_model="mistral-large-latest",
        models=("mistral-large-latest", "mistral-small-latest"),
        docs_url="https://docs.mistral.ai/",
        supports_reasoning=False, context_window=131_072, icon="mistral",
    ),
    ProviderSpec(
        id="groq", label="Groq", group="international", kind="openai",
        base_url="https://api.groq.com/openai/v1",
        default_model="llama-3.3-70b-versatile",
        models=("llama-3.3-70b-versatile", "qwen/qwen3-32b"),
        docs_url="https://console.groq.com/docs",
        supports_reasoning=False, context_window=131_072, icon="groq",
    ),
    ProviderSpec(
        id="openrouter", label="OpenRouter", group="aggregator", kind="openai",
        base_url="https://openrouter.ai/api/v1",
        default_model="anthropic/claude-sonnet-5-5",
        models=(
            "anthropic/claude-sonnet-5-5",
            "openai/gpt-4o",
            "google/gemini-2.5-pro",
        ),
        docs_url="https://openrouter.ai/docs",
        supports_reasoning=True, context_window=200_000, icon="openrouter",
    ),
    ProviderSpec(
        id="ollama", label="Ollama（本地）", group="local", kind="openai",
        base_url="http://127.0.0.1:11434/v1",
        default_model="qwen3-coder:30b",
        models=("qwen3-coder:30b", "llama3.3"),
        docs_url="https://ollama.com/",
        free_tier=True, supports_reasoning=False, context_window=32_768,
        base_url_locked=False, icon="ollama",
    ),
    ProviderSpec(
        id="custom", label="自定义 OpenAI 兼容端点", group="local", kind="openai",
        base_url="", default_model="", models=(),
        docs_url="", supports_reasoning=True, context_window=131_072,
        base_url_locked=False, icon="custom",
    ),
)

_BY_ID = {item.id: item for item in PROVIDERS}


def get_provider(provider_id: str) -> ProviderSpec | None:
    return _BY_ID.get((provider_id or "").strip().lower())


def provider_list() -> list[dict]:
    return [item.public() for item in PROVIDERS]


def resolve_base_url(spec: ProviderSpec, requested: str | None = None) -> str:
    if spec.base_url_locked:
        value = spec.public()["base_url"]
    else:
        value = (requested or spec.base_url or "").strip()
    value = value.rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Base URL 必须是 http(s) 地址")
    if parsed.hostname.lower() in BLOCKED_HOSTS:
        raise ValueError("不允许使用该地址")
    return value

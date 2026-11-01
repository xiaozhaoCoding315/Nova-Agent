import type { LlmOverrides, LlmProvider } from './types'

export function compactOverrides(value: LlmOverrides): LlmOverrides {
  const out: LlmOverrides = {}
  if (value.provider) out.provider = value.provider
  if (value.model) out.model = value.model
  if (value.reasoning_effort) out.reasoning_effort = value.reasoning_effort
  if (value.context_window != null) out.context_window = value.context_window
  if (value.temperature != null) out.temperature = value.temperature
  if (value.max_tokens != null) out.max_tokens = value.max_tokens
  return out
}

export function providerSupportsReasoning(provider?: { supports_reasoning?: boolean } | null): boolean {
  return Boolean(provider?.supports_reasoning)
}

export function providerSupportsTemperature(provider?: { supports_temperature?: boolean } | null): boolean {
  return provider?.supports_temperature !== false
}

/**
 * 按厂商能力清洗会话参数：不支持的项直接丢弃，超出上限的上下文收敛到厂商上限。
 * 用于切换厂商和发送前兜底，避免把过期/不支持的参数发给后端。
 */
export function sanitizeOverrides(
  value: LlmOverrides,
  provider?: LlmProvider | null,
): LlmOverrides {
  const out: LlmOverrides = { ...value }
  if (!provider) return out
  if (!providerSupportsReasoning(provider)) delete out.reasoning_effort
  if (!providerSupportsTemperature(provider)) delete out.temperature
  if (
    out.context_window != null
    && provider.context_window > 0
    && out.context_window > provider.context_window
  ) {
    out.context_window = provider.context_window
  }
  return out
}

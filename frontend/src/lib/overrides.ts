import type { LlmOverrides } from './types'

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

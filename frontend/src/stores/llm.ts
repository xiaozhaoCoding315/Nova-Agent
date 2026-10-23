import { create } from 'zustand'
import { api, ApiError } from '../lib/api'
import type { LlmSettings, LlmSettingsInput, LlmTestResult } from '../lib/types'

type LlmState = {
  settings: LlmSettings | null
  loading: boolean
  error: string | null
  load: () => Promise<void>
  save: (input: LlmSettingsInput) => Promise<LlmSettings>
  clear: () => Promise<void>
  test: (input: LlmSettingsInput) => Promise<LlmTestResult>
  reset: () => void
  clearError: () => void
}

export const useLlm = create<LlmState>((set) => ({
  settings: null,
  loading: false,
  error: null,

  load: async () => {
    set({ loading: true })
    try {
      set({ settings: await api.llm.get(), error: null })
    } catch (err) {
      set({ error: err instanceof ApiError ? err.message : '模型配置加载失败' })
    } finally {
      set({ loading: false })
    }
  },

  save: async (input) => {
    const settings = await api.llm.save(input)
    set({ settings, error: null })
    return settings
  },

  clear: async () => {
    set({ settings: await api.llm.clear(), error: null })
  },

  test: (input) => api.llm.test(input),

  reset: () => set({ settings: null, loading: false, error: null }),

  clearError: () => set({ error: null }),
}))

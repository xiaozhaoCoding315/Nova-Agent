import { create } from 'zustand'
import { api, ApiError } from '../lib/api'
import type { LocalSetupStatus, ModeInfo } from '../lib/types'

type ModeState = {
  mode: ModeInfo | null
  setup: LocalSetupStatus | null
  loading: boolean
  error: string | null
  load: () => Promise<ModeInfo | null>
  loadSetup: () => Promise<LocalSetupStatus | null>
  markConfigured: (status: LocalSetupStatus) => void
}

export const useMode = create<ModeState>((set, get) => ({
  mode: null,
  setup: null,
  loading: false,
  error: null,
  load: async () => {
    try {
      const mode = await api.status.mode()
      set({ mode, error: null })
      return mode
    } catch (err) {
      set({ error: err instanceof ApiError ? err.message : '无法获取运行模式' })
      return null
    }
  },
  loadSetup: async () => {
    if (!get().mode?.local) return null
    set({ loading: true })
    try {
      const setup = await api.local.setupStatus()
      set({ setup, loading: false, error: null })
      return setup
    } catch (err) {
      set({ loading: false, error: err instanceof ApiError ? err.message : '无法读取本地配置状态' })
      return null
    }
  },
  markConfigured: (status) => set({ setup: status }),
}))

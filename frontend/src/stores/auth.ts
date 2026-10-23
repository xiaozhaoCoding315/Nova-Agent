import { create } from 'zustand'
import { api, ApiError } from '../lib/api'
import type { User } from '../lib/types'

type AuthState = {
  user: User | null
  checked: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => Promise<void>
  check: () => Promise<void>
}

export const useAuth = create<AuthState>((set) => ({
  user: null,
  checked: false,

  check: async () => {
    try {
      const user = await api.me()
      set({ user, checked: true })
    } catch {
      set({ user: null, checked: true })
    }
  },

  login: async (username, password) => {
    try {
      const user = await api.login(username, password)
      set({ user })
    } catch (err) {
      throw new ApiError(err instanceof ApiError ? err.status : 0,
        err instanceof ApiError ? err.message : '登录失败')
    }
  },

  logout: async () => {
    try {
      await api.logout()
    } finally {
      set({ user: null })
    }
  },
}))
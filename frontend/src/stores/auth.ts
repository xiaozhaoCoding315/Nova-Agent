import { create } from 'zustand'
import { api, ApiError } from '../lib/api'
import type { User } from '../lib/types'
import { useChat } from './chat'
import { useLlm } from './llm'
import { useRepos } from './repos'

function resetUserData() {
  useChat.getState().reset()
  useRepos.getState().reset()
  useLlm.getState().reset()
}

type AuthState = {
  user: User | null
  checked: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => Promise<void>
  check: () => Promise<void>
}

export const useAuth = create<AuthState>((set, get) => ({
  user: null,
  checked: false,

  check: async () => {
    try {
      const user = await api.me()
      if (get().user?.id !== user.id) resetUserData()
      set({ user, checked: true })
    } catch {
      resetUserData()
      set({ user: null, checked: true })
    }
  },

  login: async (username, password) => {
    try {
      const user = await api.login(username, password)
      resetUserData()
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
      resetUserData()
      set({ user: null })
    }
  },
}))